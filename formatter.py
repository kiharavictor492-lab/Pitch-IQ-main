"""
football_bot/formatter.py
==========================
Formats messages for free channel and VIP chat.
Free posts include a teaser of locked stats + subscribe button.
"""

from datetime import datetime, timezone
from config import BOT_USERNAME, SUBSCRIPTION_AMOUNT


# ─── Utilities ────────────────────────────────────────────────────────────────

def _pct(p: float) -> str:
    return f"{round(p * 100)}%"


def _bar(p: float, width: int = 10) -> str:
    filled = round(p * width)
    return "🟩" * filled + "⬜" * (width - filled)


def _form_emoji(results: list[str]) -> str:
    icons = {"W": "🟢", "D": "🟡", "L": "🔴"}
    return " ".join(icons.get(r, "⚪") for r in results)


def _kickoff_str(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y · %H:%M UTC")
    except Exception:
        return iso


def _confidence_label(score: int) -> str:
    if score >= 80: return "🔥 HIGH"
    if score >= 60: return "✅ MODERATE"
    return "⚠️ LOW"


def _locked(text: str) -> str:
    """Replace a stat value with a lock to tease VIP content."""
    return "🔒 VIP"


# ─── FREE channel post ────────────────────────────────────────────────────────

def format_free(pred: dict) -> tuple[str, dict]:
    """
    Returns (message_text, inline_keyboard_dict) for the free channel post.
    Each post shows basic stats freely, then teases locked VIP stats,
    and ends with a subscribe button linking directly to the bot.
    """
    home = pred["home_team"]
    away = pred["away_team"]
    hw   = pred["home_win_prob"]
    d    = pred["draw_prob"]
    aw   = pred["away_win_prob"]
    go   = pred["goals_over_25"]
    gu   = pred["goals_under_25"]
    cor  = pred["corners"]
    pen  = pred["penalty_prob"]
    conf = pred.get("confidence", 0)

    msg = (
        f"⚽ <b>MATCH PREDICTION</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>{pred['league']}</b>\n"
        f"📅 {_kickoff_str(pred['kickoff_utc'])}\n\n"

        f"🆚 <b>{home}  vs  {away}</b>\n\n"

        # ── Freely visible ────────────────────────────────────────────────────
        f"📊 <b>WIN PROBABILITY</b>\n"
        f"🏠 {home:<20} {_bar(hw)} {_pct(hw)}\n"
        f"🤝 Draw{'':<17} {_bar(d)}  {_pct(d)}\n"
        f"✈️ {away:<20} {_bar(aw)} {_pct(aw)}\n\n"

        f"⚽ <b>GOALS</b>\n"
        f"  Over 2.5    {_bar(go)}  {_pct(go)}\n"
        f"  Under 2.5   {_bar(gu)}  {_pct(gu)}\n\n"

        f"🚩 <b>CORNERS</b>\n"
        f"  Expected: ~{cor['expected_total']}  |  "
        f"Over {cor['over_line']}: {_pct(cor['over_prob'])}\n\n"

        f"🥅 <b>PENALTY CHANCE</b>  {_pct(pen)}\n\n"

        # ── Locked VIP teaser ─────────────────────────────────────────────────
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔐 <b>VIP STATS — UNLOCK BELOW</b>\n\n"

        f"🎯 Confidence Score:      {_locked('conf')}\n"
        f"📈 Last 5 Form:           {_locked('form')}\n"
        f"🔄 Head-to-Head Record:   {_locked('h2h')}\n"
        f"⚡ Expected Goals (xG):   {_locked('xg')}\n"
        f"🎯 BTTS Probability:      {_locked('btts')}\n"
        f"💡 Bet Tips (1X2/O-U):   {_locked('tips')}\n"
        f"🤖 AI Match Analysis:     {_locked('ai')}\n\n"

        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>Get the full picture for just KSh {SUBSCRIPTION_AMOUNT}/day</b>\n"
        f"Chat the bot privately → subscribe → get all stats instantly with /tips"
    )

    # Inline button — deep-links directly into the bot
    keyboard = {
        "inline_keyboard": [[
            {
                "text": f"💎 Get Full Analysis — KSh {SUBSCRIPTION_AMOUNT}/day",
                "url": f"https://t.me/{BOT_USERNAME}?start=subscribe"
            }
        ]]
    }

    return msg, keyboard


# ─── Free channel daily header ────────────────────────────────────────────────

def format_daily_header(count: int, channel_type: str = "free") -> tuple[str, None]:
    today = datetime.now(timezone.utc).strftime("%A, %d %B %Y")
    if channel_type == "vip":
        return (
            f"💎 <b>VIP DAILY PREDICTIONS</b> 💎\n"
            f"📅 {today}\n"
            f"📋 {count} match{'es' if count != 1 else ''} analysed\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
        ), None
    return (
        f"⚽ <b>TODAY'S FREE PREDICTIONS</b>\n"
        f"📅 {today}\n"
        f"📋 {count} match{'es' if count != 1 else ''} today\n"
        f"💎 Full VIP analysis available — tap the button under each match!\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
    ), None


# ─── VIP chat message ────────────────────────────────────────────────────────

def _tips_block(pred: dict) -> str:
    tips = []

    top = pred["top_outcome"]
    if pred["top_prob"] > 0.50:
        tips.append(f"✅ <b>1X2:</b> {top} ({_pct(pred['top_prob'])})")
    else:
        tips.append(f"⚠️ <b>1X2:</b> No clear favourite")

    if pred["goals_over_25"] > 0.60:
        tips.append(f"✅ <b>Goals:</b> Over 2.5 ({_pct(pred['goals_over_25'])})")
    elif pred["goals_under_25"] > 0.60:
        tips.append(f"✅ <b>Goals:</b> Under 2.5 ({_pct(pred['goals_under_25'])})")
    else:
        tips.append(f"⚠️ <b>Goals:</b> 50/50 — skip Over/Under")

    btts = pred["btts_prob"]
    tips.append(f"⚽ <b>BTTS:</b> {'Yes' if btts > 0.55 else 'No'} ({_pct(btts)})")

    cor = pred["corners"]
    if cor["over_prob"] > 0.62:
        tips.append(f"🚩 <b>Corners:</b> Over {cor['over_line']} ({_pct(cor['over_prob'])})")
    elif cor["under_prob"] > 0.62:
        tips.append(f"🚩 <b>Corners:</b> Under {cor['over_line']} ({_pct(cor['under_prob'])})")

    if pred["penalty_prob"] > 0.35:
        tips.append(f"🥅 <b>Penalty:</b> Likely ({_pct(pred['penalty_prob'])})")

    return "\n".join(f"  {t}" for t in tips)


def format_vip(pred: dict, ai_narrative: str = "") -> str:
    home = pred["home_team"]
    away = pred["away_team"]
    hw   = pred["home_win_prob"]
    d    = pred["draw_prob"]
    aw   = pred["away_win_prob"]
    cor  = pred["corners"]
    h2h  = pred["h2h"]
    conf = pred["confidence"]

    msg = (
        f"💎 <b>VIP PREDICTION REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>{pred['league']}</b>\n"
        f"📅 {_kickoff_str(pred['kickoff_utc'])}\n\n"

        f"🆚 <b>{home}  vs  {away}</b>\n"
        f"🎯 Confidence: {_confidence_label(conf)}  [{conf}/100]\n\n"

        f"📊 <b>WIN PROBABILITY</b>\n"
        f"🏠 {home:<20} {_bar(hw)} {_pct(hw)}\n"
        f"🤝 Draw{'':<17} {_bar(d)}  {_pct(d)}\n"
        f"✈️ {away:<20} {_bar(aw)} {_pct(aw)}\n\n"

        f"📈 <b>FORM (last 5)</b>\n"
        f"  {home}: {_form_emoji(pred['home_form'])}\n"
        f"  {away}: {_form_emoji(pred['away_form'])}\n\n"

        f"🔄 <b>HEAD TO HEAD ({h2h['matches']} games)</b>\n"
        f"  {home} wins: {h2h['home_wins']}  |  "
        f"Draws: {h2h['draws']}  |  {away} wins: {h2h['away_wins']}\n"
        f"  Avg goals/game: {h2h['avg_goals']}\n\n"

        f"⚽ <b>GOALS</b>\n"
        f"  xG → {home}: {pred['home_xg']}  |  {away}: {pred['away_xg']}\n"
        f"  Over 2.5:   {_bar(pred['goals_over_25'])} {_pct(pred['goals_over_25'])}\n"
        f"  Under 2.5:  {_bar(pred['goals_under_25'])} {_pct(pred['goals_under_25'])}\n"
        f"  BTTS:       {_pct(pred['btts_prob'])}\n\n"

        f"🚩 <b>CORNERS</b>\n"
        f"  Expected: ~{cor['expected_total']}\n"
        f"  Over {cor['over_line']}: {_pct(cor['over_prob'])}  |  "
        f"Under: {_pct(cor['under_prob'])}\n\n"

        f"🥅 <b>PENALTY PROBABILITY</b>\n"
        f"  {_pct(pred['penalty_prob'])} chance of a penalty\n\n"

        f"💡 <b>BET TIPS</b>\n"
        f"{_tips_block(pred)}\n"
    )

    if pred.get("injuries"):
        msg += "\n🚑 <b>INJURIES / SUSPENSIONS</b>\n"
        for inj in pred["injuries"][:6]:
            msg += f"  ❌ {inj}\n"
        msg += "\n"

    if ai_narrative:
        msg += f"\n🤖 <b>AI ANALYSIS</b>\n<i>{ai_narrative}</i>\n"

    msg += (
        "\n━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <i>For informational purposes only. Gamble responsibly.</i>"
    )
    return msg