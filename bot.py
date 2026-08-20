"""
football_bot/bot.py
====================
On-demand VIP predictions with match picker:

  /tips  → shows two buttons:
           [⚽ All Matches]  [🔍 Pick a Match]

  All Matches  → sends every match one by one
  Pick a Match → shows inline keyboard with each match as a button
                 → tap a match → get that match's full analysis only

Cache is built ONCE daily. All /tips requests served from cache instantly.
Bot only responds to commands — never pushes unsolicited messages.
"""

import logging
import asyncio
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

from config import (
    TELEGRAM_BOT_TOKEN, FREE_CHANNEL_ID, ADMIN_CHAT_IDS,
    SCHEDULE_TIME_UTC, SUBSCRIPTION_AMOUNT, SUBSCRIPTION_DAYS,
)
from database import (
    init_db, add_subscriber, get_active_subscribers,
    is_active_subscriber, get_subscriber_expiry, is_returning_user,
    save_pending_payment, get_pending_by_user,
    mark_payment, log_delivery, already_delivered_today,
    deactivate_expired, get_stats,
)
from mpesa       import stk_push, query_payment
from fetcher     import get_todays_fixtures, enrich_fixture
from analyser    import analyse
from formatter   import format_free, format_vip, format_daily_header
from ai_narrator import generate_narrative
from publisher   import post_to_free

import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_PHONE = 1
TG_DELAY      = 1.2   # seconds between messages to avoid Telegram flood limit


# ══════════════════════════════════════════════════════════════════════════════
# Prediction Cache
# ══════════════════════════════════════════════════════════════════════════════

class PredictionCache:
    """
    In-memory store for today's predictions.
    Built once by the scheduler, served instantly to all /tips requests.
    """
    def __init__(self):
        self.predictions:  list[dict] = []   # raw prediction dicts
        self.vip_messages: list[str]  = []   # formatted VIP strings
        self.free_messages: list[str] = []   # formatted free strings
        self.built_at: str | None     = None
        self.date:     str | None     = None

    def is_fresh(self) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.date == today and len(self.predictions) > 0

    def clear(self):
        self.predictions  = []
        self.vip_messages = []
        self.free_messages = []
        self.built_at     = None
        self.date         = None

    @property
    def match_count(self) -> int:
        return len(self.predictions)

    @property
    def built_time_str(self) -> str:
        if not self.built_at:
            return "not built"
        try:
            return datetime.fromisoformat(self.built_at).strftime("%H:%M UTC")
        except Exception:
            return self.built_at


_cache = PredictionCache()


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_CHAT_IDS


def _expiry_str(user_id: int) -> str:
    exp = get_subscriber_expiry(user_id)
    if not exp:
        return "No active subscription"
    try:
        return datetime.fromisoformat(exp).strftime("%d %b %Y")
    except Exception:
        return exp


async def _send(bot, chat_id: int, text: str, parse_mode: str = "HTML",
                reply_markup=None) -> bool:
    """Send safely, swallowing errors."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
        return True
    except Exception as e:
        logger.error(f"Send error to {chat_id}: {e}")
        return False


def _vip_gate_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💎 Subscribe – KSh 50/day", callback_data="subscribe")
    ]])


def _not_ready_msg() -> str:
    return (
        f"⏳ <b>Predictions not ready yet</b>\n\n"
        f"Today's analysis is built at <b>{SCHEDULE_TIME_UTC} UTC</b>.\n"
        f"Check back soon, or ask the admin to run /build."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Match picker keyboard builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_match_keyboard() -> InlineKeyboardMarkup:
    """
    Creates an inline keyboard where each button = one match.
    Button label: "Home vs Away  HH:MM"
    Callback data: "match_<index>"  (0-based index into cache)
    Buttons are arranged 1 per row for readability.
    """
    buttons = []
    for i, pred in enumerate(_cache.predictions):
        try:
            ko       = datetime.fromisoformat(pred["kickoff_utc"].replace("Z", "+00:00"))
            time_str = ko.strftime("%H:%M")
        except Exception:
            time_str = "TBD"

        label = f"⚽ {pred['home_team']} vs {pred['away_team']}  🕐{time_str}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"match_{i}")])

    # Add "All matches" button at top
    buttons.insert(0, [InlineKeyboardButton(
        f"📋 All {_cache.match_count} Matches at Once", callback_data="tips_all"
    )])
    return InlineKeyboardMarkup(buttons)


# ══════════════════════════════════════════════════════════════════════════════
# Cache builder  (only place where API calls happen)
# ══════════════════════════════════════════════════════════════════════════════

async def build_cache(notify_chat_id: int | None = None, bot=None):
    """
    Fetch, analyse and store all today's predictions.
    Called once by scheduler or admin /build.
    """
    logger.info("🔄 Building prediction cache...")

    async def _notify(text: str):
        if notify_chat_id and bot:
            await _send(bot, notify_chat_id, text)

    await _notify("⏳ Fetching today's fixtures from football-data.org…")

    fixtures = get_todays_fixtures()
    if not fixtures:
        _cache.clear()
        await _notify("ℹ️ No fixtures found for today. Cache not built.")
        return

    await _notify(
        f"✅ <b>{len(fixtures)} fixtures found</b>\n"
        f"⏳ Analysing matches now (takes a few minutes due to free API limits)…"
    )

    predictions   = []
    vip_messages  = []
    free_messages = [format_daily_header(len(fixtures), "free")]

    for i, fixture in enumerate(fixtures):
        home = fixture["home"]["name"]
        away = fixture["away"]["name"]
        logger.info(f"  [{i+1}/{len(fixtures)}] {home} vs {away}")

        # Notify admin every 3 matches so they know it's still working
        if notify_chat_id and bot and i > 0 and i % 3 == 0:
            await _send(bot, notify_chat_id,
                f"⚙️ [{i+1}/{len(fixtures)}] Analysing {home} vs {away}…")

        try:
            enriched  = enrich_fixture(fixture)
            pred      = analyse(enriched)
            narrative = generate_narrative(pred)

            predictions.append(pred)
            free_messages.append(format_free(pred))
            vip_messages.append(format_vip(pred, ai_narrative=narrative))

            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"  Error on fixture {i+1}: {e}")
            continue

    now = datetime.now(timezone.utc)
    _cache.predictions   = predictions
    _cache.vip_messages  = vip_messages
    _cache.free_messages = free_messages
    _cache.built_at      = now.isoformat()
    _cache.date          = now.strftime("%Y-%m-%d")

    logger.info(f"✅ Cache built — {len(predictions)} predictions")
    await _notify(
        f"✅ <b>Cache ready!</b>\n"
        f"⚽ {len(predictions)} matches analysed\n"
        f"🕐 Built at {_cache.built_time_str}\n\n"
        f"VIP users can now use /tips to get predictions."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Daily scheduler job
# ══════════════════════════════════════════════════════════════════════════════

async def run_daily_job(app: Application):
    logger.info("⏰ Daily job starting…")
    deactivate_expired()

    for admin_id in ADMIN_CHAT_IDS:
        await _send(app.bot, admin_id,
            f"⏰ <b>Daily job started</b>\n"
            f"📅 {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}")

    await build_cache(
        notify_chat_id=ADMIN_CHAT_IDS[0] if ADMIN_CHAT_IDS else None,
        bot=app.bot,
    )

    if not _cache.is_fresh():
        return

    # Post free predictions to channel (header has no button, each match has subscribe button)
    logger.info("Posting to free channel…")
    for item in _cache.free_messages:
        if isinstance(item, tuple):
            msg_text, keyboard = item
            post_to_free(msg_text, keyboard)
        else:
            post_to_free(item)
        await asyncio.sleep(TG_DELAY)

    logger.info("Daily job complete. VIP users can now /tips.")


# ══════════════════════════════════════════════════════════════════════════════
# Sending helpers
# ══════════════════════════════════════════════════════════════════════════════

async def _send_single_match(bot, uid: int, index: int):
    """Send VIP analysis for one specific match by cache index."""
    if index < 0 or index >= _cache.match_count:
        await _send(bot, uid, "❌ Match not found. Use /tips to see the list again.")
        return

    pred    = _cache.predictions[index]
    vip_msg = _cache.vip_messages[index]

    try:
        ko       = datetime.fromisoformat(pred["kickoff_utc"].replace("Z", "+00:00"))
        time_str = ko.strftime("%H:%M UTC")
    except Exception:
        time_str = "TBD"

    header = (
        f"💎 <b>Match Analysis</b>\n"
        f"⚽ <b>{pred['home_team']} vs {pred['away_team']}</b>\n"
        f"🕐 Kick-off: {time_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    await _send(bot, uid, header + vip_msg)
    await asyncio.sleep(0.5)

    # Back button so user can pick another match
    back_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Pick Another Match", callback_data="tips_pick"),
        InlineKeyboardButton("📋 All Matches",        callback_data="tips_all"),
    ]])
    await _send(bot, uid,
        "👆 Done! Want to see another match?",
        reply_markup=back_keyboard,
    )


async def _send_all_matches(bot, uid: int, user_name: str = "Champ"):
    """Send all VIP match analyses one by one."""
    today_str = datetime.now(timezone.utc).strftime("%A, %d %B %Y")

    await _send(bot, uid,
        f"💎 <b>PitchIQ VIP — All Predictions</b>\n"
        f"👋 Here you go, {user_name}!\n\n"
        f"📅 {today_str}\n"
        f"⚽ <b>{_cache.match_count} matches today</b>\n"
        f"🕐 Analysis built at {_cache.built_time_str}\n\n"
        f"Sending each match now 👇"
    )
    await asyncio.sleep(0.8)

    for i, vip_msg in enumerate(_cache.vip_messages, 1):
        try:
            pred = _cache.predictions[i - 1]
            ko   = datetime.fromisoformat(pred["kickoff_utc"].replace("Z", "+00:00"))
            ko_str = ko.strftime("%H:%M UTC")
        except Exception:
            ko_str = "TBD"

        header = (
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚽ <b>Match {i} of {_cache.match_count}</b>  🕐 {ko_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        await _send(bot, uid, header + vip_msg)
        await asyncio.sleep(TG_DELAY)

    await _send(bot, uid,
        f"✅ <b>All {_cache.match_count} matches done!</b>\n\n"
        f"💡 Use /tips anytime to read them again.\n"
        f"📅 Sub expires: {_expiry_str(uid)}\n\n"
        f"⚠️ <i>For informational purposes only. Gamble responsibly.</i>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Renew Subscription", callback_data="subscribe")
        ]])
    )
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_delivery(uid, today, "sent")


# ══════════════════════════════════════════════════════════════════════════════
# /tips  command
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_tips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = update.effective_user

    # Gate: VIP only
    if not is_active_subscriber(uid) and not _is_admin(uid):
        if is_returning_user(uid):
            # Expired subscriber — show renew prompt
            await update.message.reply_text(
                "⏰ <b>Your subscription has expired</b>\n\n"
                f"Renew for <b>KSh {SUBSCRIPTION_AMOUNT}/day</b> to get back:\n\n"
                "  ✅ Full match-by-match analysis\n"
                "  ✅ xG, BTTS, corners, penalties, AI tips\n"
                "  ✅ Pick any match or get them all\n\n"
                "👇 Renew now via M-Pesa — takes 30 seconds:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Renew – KSh 50/day", callback_data="subscribe")
                ]]),
            )
        else:
            # First time visitor
            await update.message.reply_text(
                "🔒 <b>VIP access required</b>\n\n"
                f"Subscribe for <b>KSh {SUBSCRIPTION_AMOUNT}/day</b> to unlock /tips:\n\n"
                "  ✅ Full analysis for every match today\n"
                "  ✅ xG, BTTS, corners, penalties, AI tips\n"
                "  ✅ Pick one match or get them all\n"
                "  ✅ Use it anytime, as many times as you want\n\n"
                "👇 Subscribe instantly via M-Pesa:",
                parse_mode="HTML",
                reply_markup=_vip_gate_keyboard(),
            )
        return

    # Gate: cache must be fresh
    if not _cache.is_fresh():
        await update.message.reply_text(_not_ready_msg(), parse_mode="HTML")
        return

    if _cache.match_count == 0:
        await update.message.reply_text(
            "😔 <b>No matches today</b>\n\nCheck back tomorrow!",
            parse_mode="HTML",
        )
        return

    # Show the pick menu
    name = user.first_name or "Champ"
    today_str = datetime.now(timezone.utc).strftime("%A, %d %B %Y")

    await update.message.reply_text(
        f"💎 <b>PitchIQ VIP Predictions</b>\n"
        f"👋 Hey {name}!\n\n"
        f"📅 {today_str}\n"
        f"⚽ <b>{_cache.match_count} matches analysed</b>\n"
        f"🕐 Ready since {_cache.built_time_str}\n"
        f"📅 Sub expires: {_expiry_str(uid)}\n\n"
        f"How would you like to receive the predictions?",
        parse_mode="HTML",
        reply_markup=_build_match_keyboard(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# /matches  (free preview for everyone)
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _cache.is_fresh() or _cache.match_count == 0:
        await update.message.reply_text(
            f"📋 No matches loaded yet.\n"
            f"Check back after {SCHEDULE_TIME_UTC} UTC."
        )
        return

    lines = [
        f"📋 <b>Today's Matches — {_cache.match_count} games</b>\n"
        f"📅 {datetime.now(timezone.utc).strftime('%d %b %Y')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    for i, pred in enumerate(_cache.predictions, 1):
        try:
            ko  = datetime.fromisoformat(pred["kickoff_utc"].replace("Z", "+00:00"))
            ko_str = ko.strftime("%H:%M")
        except Exception:
            ko_str = "TBD"
        lines.append(
            f"{i}. <b>{pred['home_team']}</b> vs <b>{pred['away_team']}</b>\n"
            f"   🏆 {pred['league']}  |  🕐 {ko_str} UTC"
        )

    uid = update.effective_user.id
    if is_active_subscriber(uid) or _is_admin(uid):
        lines.append("\n💎 Use /tips to get full analysis — pick a match or get them all!")
    else:
        lines.append(
            "\n━━━━━━━━━━━━━━━━━━━━━\n"
            "💎 /tips gives full analysis for any match above\n"
            "(VIP only — /subscribe to join for KSh 50/day)"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════════════════
# Inline button callbacks
# ══════════════════════════════════════════════════════════════════════════════

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    data = query.data

    # ── Subscribe button ──────────────────────────────────────────────────────
    if data == "subscribe":
        await cmd_subscribe(update, context)
        return

    # ── All matches button ────────────────────────────────────────────────────
    if data == "tips_all":
        if not is_active_subscriber(uid) and not _is_admin(uid):
            await query.message.reply_text(
                "🔒 VIP access required. Use /subscribe.",
                reply_markup=_vip_gate_keyboard(),
            )
            return
        if not _cache.is_fresh():
            await query.message.reply_text(_not_ready_msg(), parse_mode="HTML")
            return
        name = query.from_user.first_name or "Champ"
        await query.message.reply_text(f"⏳ Sending all {_cache.match_count} matches…")
        await _send_all_matches(context.bot, uid, user_name=name)
        return

    # ── Pick menu button ──────────────────────────────────────────────────────
    if data == "tips_pick":
        if not is_active_subscriber(uid) and not _is_admin(uid):
            await query.message.reply_text(
                "🔒 VIP access required. Use /subscribe.",
                reply_markup=_vip_gate_keyboard(),
            )
            return
        if not _cache.is_fresh():
            await query.message.reply_text(_not_ready_msg(), parse_mode="HTML")
            return
        await query.message.reply_text(
            "🔍 <b>Pick a match:</b>",
            parse_mode="HTML",
            reply_markup=_build_match_keyboard(),
        )
        return

    # ── Specific match button: match_<index> ──────────────────────────────────
    if data.startswith("match_"):
        if not is_active_subscriber(uid) and not _is_admin(uid):
            await query.message.reply_text(
                "🔒 VIP access required. Use /subscribe.",
                reply_markup=_vip_gate_keyboard(),
            )
            return
        if not _cache.is_fresh():
            await query.message.reply_text(_not_ready_msg(), parse_mode="HTML")
            return
        try:
            index = int(data.split("_")[1])
        except ValueError:
            await query.message.reply_text("❌ Invalid selection.")
            return
        await query.message.reply_text(
            f"⏳ Loading analysis for match {index + 1}…"
        )
        await _send_single_match(context.bot, uid, index)
        return

    # ── get_tips shortcut (from /start button) ────────────────────────────────
    if data == "get_tips":
        if not is_active_subscriber(uid) and not _is_admin(uid):
            await query.message.reply_text(
                "🔒 VIP access required. Use /subscribe.",
                reply_markup=_vip_gate_keyboard(),
            )
            return
        if not _cache.is_fresh():
            await query.message.reply_text(_not_ready_msg(), parse_mode="HTML")
            return
        name = query.from_user.first_name or "Champ"
        today_str = datetime.now(timezone.utc).strftime("%A, %d %B %Y")
        await query.message.reply_text(
            f"💎 <b>PitchIQ VIP Predictions</b>\n"
            f"👋 Hey {name}!\n\n"
            f"📅 {today_str}\n"
            f"⚽ <b>{_cache.match_count} matches ready</b>\n"
            f"🕐 Built at {_cache.built_time_str}\n\n"
            f"Pick a match or get them all:",
            parse_mode="HTML",
            reply_markup=_build_match_keyboard(),
        )
        return


# ══════════════════════════════════════════════════════════════════════════════
# /start
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid  = user.id

    if is_active_subscriber(uid) or _is_admin(uid):
        keyboard = [
            [InlineKeyboardButton("⚽ Get Today's Tips",  callback_data="get_tips")],
            [InlineKeyboardButton("📋 Today's Matches",   callback_data="get_matches")],
            [InlineKeyboardButton("🔄 Renew",             callback_data="subscribe")],
        ]
        await update.message.reply_text(
            f"👋 Welcome back, <b>{user.first_name}</b>!\n\n"
            f"💎 VIP Status: <b>ACTIVE</b>\n"
            f"📅 Expires: {_expiry_str(uid)}\n\n"
            f"Use /tips anytime to get today's predictions.\n"
            f"Pick a specific match or load them all!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    keyboard = [[InlineKeyboardButton("💎 Subscribe – KSh 50/day", callback_data="subscribe")]]
    await update.message.reply_text(
        f"⚽ <b>Welcome to PitchIQ!</b>\n\n"
        f"Expert football predictions, on demand.\n\n"
        f"🆓 <b>Free:</b>\n"
        f"  /matches — see today's match list\n\n"
        f"💎 <b>VIP – KSh 50/day:</b>\n"
        f"  /tips — pick any match or get them all\n"
        f"  ✅ Win %, xG, BTTS, corners, penalties\n"
        f"  ✅ Form, H2H, standings, confidence\n"
        f"  ✅ AI narrative & bet tips\n"
        f"  ✅ Use anytime, as many times as you want\n\n"
        f"💳 Pay via M-Pesa — instant activation!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Subscribe conversation
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if update.callback_query:
        await update.callback_query.answer()
        reply = update.callback_query.message.reply_text
    else:
        reply = update.message.reply_text

    if is_active_subscriber(uid):
        await reply(
            f"✅ Already subscribed!\n"
            f"📅 Expires: {_expiry_str(uid)}\n\n"
            f"Use /tips to get today's predictions."
        )
        return ConversationHandler.END

    await reply(
        f"📱 Enter your <b>M-Pesa phone number</b>:\n\n"
        f"Format: <code>07XXXXXXXX</code>\n\n"
        f"KSh <b>{SUBSCRIPTION_AMOUNT}</b> will be charged.",
        parse_mode="HTML",
    )
    return WAITING_PHONE


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    uid   = update.effective_user.id
    user  = update.effective_user

    clean = phone.replace("+", "").replace(" ", "").replace("-", "")
    if not any(clean.startswith(p) for p in ["07", "01", "2547", "2541"]):
        await update.message.reply_text(
            "❌ Invalid number. Example: <code>0712345678</code>",
            parse_mode="HTML",
        )
        return WAITING_PHONE

    await update.message.reply_text(
        f"⏳ Sending KSh {SUBSCRIPTION_AMOUNT} STK push to <b>{phone}</b>…\n"
        f"📲 Enter your M-Pesa PIN when prompted.",
        parse_mode="HTML",
    )

    result = stk_push(phone, uid)
    if not result["success"]:
        await update.message.reply_text(
            f"❌ Failed: {result.get('error', 'Unknown error')}\n"
            f"Try again with /subscribe"
        )
        return ConversationHandler.END

    checkout_id = result["checkout_request_id"]
    save_pending_payment(checkout_id, uid, phone, SUBSCRIPTION_AMOUNT)

    await update.message.reply_text(
        "📲 STK push sent!\n\n"
        "1️⃣ Enter your PIN on your phone\n"
        "2️⃣ Then send /confirm to activate\n\n"
        "The bot will also auto-check in 30 seconds."
    )

    context.application.job_queue.run_once(
        _auto_check,
        when=30,
        data={
            "checkout_id": checkout_id,
            "user_id":     uid,
            "phone":       phone,
            "full_name":   user.full_name or user.first_name,
        },
    )
    return ConversationHandler.END


async def cmd_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    pending = get_pending_by_user(uid)
    if not pending:
        await update.message.reply_text("No pending payment. Use /subscribe to start.")
        return
    await _check_and_activate(
        update.message.reply_text,
        pending["checkout_request_id"], uid,
        pending["phone"],
        update.effective_user.full_name or update.effective_user.first_name,
    )


async def _auto_check(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    async def send(text, **kw):
        await context.bot.send_message(d["user_id"], text, **kw)
    await _check_and_activate(send, d["checkout_id"], d["user_id"], d["phone"], d["full_name"])


async def _check_and_activate(send_fn, checkout_id, uid, phone, full_name):
    result = query_payment(checkout_id)
    if result["paid"]:
        mark_payment(checkout_id, "confirmed")
        add_subscriber(uid, "", full_name, phone)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⚽ Get Today's Tips", callback_data="get_tips")
        ]])
        await send_fn(
            f"🎉 <b>Payment confirmed! Welcome to VIP!</b>\n\n"
            f"💎 Subscription active for {SUBSCRIPTION_DAYS} day(s)\n"
            f"📅 Expires: {_expiry_str(uid)}\n\n"
            f"Tap below or type /tips to get today's predictions!",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    elif result["reason"] == "cancelled":
        mark_payment(checkout_id, "cancelled")
        await send_fn("❌ Payment cancelled. Use /subscribe to try again.")
    else:
        await send_fn(
            f"⏳ Not confirmed yet ({result['reason']}).\n"
            f"If you paid, send /confirm again in a moment."
        )


# ══════════════════════════════════════════════════════════════════════════════
# /status
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_active_subscriber(uid):
        await update.message.reply_text(
            f"💎 <b>VIP Status: ACTIVE</b>\n"
            f"📅 Expires: {_expiry_str(uid)}\n\n"
            f"Cache: {'✅ Ready — ' + str(_cache.match_count) + ' matches' if _cache.is_fresh() else '⏳ Not yet built'}\n\n"
            f"Use /tips to get today's predictions.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚽ Get Tips",  callback_data="get_tips"),
                InlineKeyboardButton("🔄 Renew",     callback_data="subscribe"),
            ]]),
        )
    else:
        await update.message.reply_text(
            "❌ <b>No active subscription</b>\n\n"
            "Subscribe to unlock /tips with full match analysis.",
            parse_mode="HTML",
            reply_markup=_vip_gate_keyboard(),
        )


# ══════════════════════════════════════════════════════════════════════════════
# Admin commands
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_build(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: manually build/rebuild the cache."""
    if not _is_admin(update.effective_user.id):
        # Non-admin trying /build — check if they're a subscriber
        uid = update.effective_user.id
        if is_active_subscriber(uid):
            await update.message.reply_text(
                "💡 You don't need /build — that's an admin command.\n\n"
                "Use /tips to get today's predictions instead!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚽ Get Tips", callback_data="get_tips")
                ]]),
            )
        elif is_returning_user(uid):
            await update.message.reply_text(
                "⏰ <b>Your subscription has expired</b>\n\n"
                "Renew to access predictions again.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Renew – KSh 50/day", callback_data="subscribe")
                ]]),
            )
        else:
            await update.message.reply_text(
                "⛔ This command is for admins only.\n\n"
                "Use /tips to get predictions (VIP subscription required).",
                reply_markup=_vip_gate_keyboard(),
            )
        return

    # Admin: check if cache is already fresh
    if _cache.is_fresh():
        await update.message.reply_text(
            f"✅ <b>Cache is already built for today!</b>\n\n"
            f"⚽ {_cache.match_count} matches ready\n"
            f"🕐 Built at {_cache.built_time_str}\n\n"
            f"Use /tips to get the predictions, or /cache to check details.\n\n"
            f"To force a rebuild anyway, use /rebuild",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚽ Get Tips", callback_data="get_tips")
            ]]),
        )
        return

    await update.message.reply_text(
        "⚙️ Building cache now…\n"
        "⚠️ Takes a few minutes due to free API rate limits."
    )
    await build_cache(notify_chat_id=update.effective_user.id, bot=context.bot)
    if _cache.is_fresh():
        for item in _cache.free_messages:
            if isinstance(item, tuple):
                msg_text, keyboard = item
                post_to_free(msg_text, keyboard)
            else:
                post_to_free(item)
            await asyncio.sleep(TG_DELAY)
        await update.message.reply_text("✅ Free channel updated too!")


async def cmd_rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: force rebuild cache even if already fresh."""
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    _cache.clear()
    await update.message.reply_text(
        "🔄 Cache cleared. Rebuilding from scratch…\n"
        "⚠️ Takes a few minutes."
    )
    await build_cache(notify_chat_id=update.effective_user.id, bot=context.bot)
    if _cache.is_fresh():
        for item in _cache.free_messages:
            if isinstance(item, tuple):
                msg_text, keyboard = item
                post_to_free(msg_text, keyboard)
            else:
                post_to_free(item)
            await asyncio.sleep(TG_DELAY)
        await update.message.reply_text("✅ Free channel updated!")


async def cmd_cache_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.reply_text(
        f"🗄️ <b>Cache Status</b>\n\n"
        f"Fresh today:  {'✅ Yes' if _cache.is_fresh() else '❌ No'}\n"
        f"Built at:     {_cache.built_time_str}\n"
        f"Matches:      {_cache.match_count}\n",
        parse_mode="HTML",
    )


async def cmd_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    stats = get_stats()
    await update.message.reply_text(
        f"📊 <b>PitchIQ Stats</b>\n\n"
        f"👥 Total subscribers:  {stats['total_subscribers']}\n"
        f"✅ Active now:         {stats['active']}\n"
        f"💰 Confirmed payments: {stats['total_payments']}\n"
        f"📨 Tips served today:  {stats['sent_today']}\n"
        f"⚽ Matches in cache:   {_cache.match_count}\n",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    vip = is_active_subscriber(uid) or _is_admin(uid)
    msg = (
        "⚽ <b>PitchIQ Commands</b>\n\n"
        "/start      – Welcome & pricing\n"
        "/matches    – Today's match list (free)\n"
        "/subscribe  – Pay via M-Pesa\n"
        "/confirm    – Confirm M-Pesa payment\n"
        "/status     – Your subscription status\n"
        "/help       – This message\n"
    )
    if vip:
        msg += (
            "\n💎 <b>VIP Commands</b>\n"
            "/tips — Get predictions (pick a match or all)\n"
        )
    await update.message.reply_text(msg, parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    init_db()
    logger.info("🚀 Starting PitchIQ Bot…")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("subscribe", cmd_subscribe),
            CallbackQueryHandler(cmd_subscribe, pattern="^subscribe$"),
        ],
        states={
            WAITING_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(conv)
    app.add_handler(CommandHandler("confirm", cmd_confirm))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("tips",    cmd_tips))
    app.add_handler(CommandHandler("matches", cmd_matches))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("build",   cmd_build))
    app.add_handler(CommandHandler("rebuild", cmd_rebuild))
    app.add_handler(CommandHandler("cache",   cmd_cache_status))
    app.add_handler(CommandHandler("stats",   cmd_admin_stats))
    app.add_handler(CallbackQueryHandler(handle_callbacks))

    scheduler = AsyncIOScheduler(timezone=pytz.utc)
    hour, minute = map(int, SCHEDULE_TIME_UTC.split(":"))

    async def scheduled_job():
        await run_daily_job(app)

    scheduler.add_job(scheduled_job, "cron", hour=hour, minute=minute)
    scheduler.start()
    logger.info(f"⏰ Daily cache build scheduled at {SCHEDULE_TIME_UTC} UTC")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()