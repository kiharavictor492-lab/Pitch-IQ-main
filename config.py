"""
football_bot/config.py
=======================
Reads credentials from environment variables (set these on Render).
Falls back to the literal string for local testing if you prefer —
but for production, ALWAYS use environment variables so secrets
never get committed to GitHub.
"""

import os

# ─── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8257518569:AAH2n2SkoW4f_kelcqokNVM7cb2cL5JOscM")
FREE_CHANNEL_ID    = os.environ.get("FREE_CHANNEL_ID", "@PitchIQ_vip")
BOT_USERNAME       = os.environ.get("BOT_USERNAME", "PitchIQ_Bot")  # no @
ADMIN_CHAT_IDS_RAW = os.environ.get("ADMIN_CHAT_IDS", "8225041564")
ADMIN_CHAT_IDS     = [int(x.strip()) for x in ADMIN_CHAT_IDS_RAW.split(",") if x.strip()]

# ─── football-data.org (FREE key) ────────────────────────────────────────────
FOOTBALL_DATA_ORG_KEY = os.environ.get("FOOTBALL_DATA_ORG_KEY", "625f3bda19c04ee7a5963d12b9219032")

# ─── Leagues to track ─────────────────────────────────────────────────────────
TRACKED_LEAGUE_CODES = [
    "PL",   # Premier League
    "BL1",  # Bundesliga
    "SA",   # Serie A
    "PD",   # Primera Division (La Liga)
    "FL1",  # Ligue 1
    "CL",   # UEFA Champions League
    "ELC",  # Championship
    "DED",  # Eredivisie
    "PPL",  # Primeira Liga
    "BSA",  # Campeonato Brasileiro Série A
    "EC",   # European Championship
    "WC",   # FIFA World Cup
]

# ─── M-Pesa Daraja ───────────────────────────────────────────────────────────
MPESA_ENV             = os.environ.get("MPESA_ENV", "production")
MPESA_CONSUMER_KEY    = os.environ.get("MPESA_CONSUMER_KEY", "f38r7FiB5IzKxbbbHyNBS7es3A3aL3TYXGXZQj1kX7CIlLXJ")
MPESA_CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "kHTzSaFkrw4haMhJSUilDy8QHHeQiLL4QM3ylAkMGAHgsNKQNIzolXYrWoeRsgyE")
MPESA_SHORTCODE       = os.environ.get("MPESA_SHORTCODE", "4490158")
MPESA_PASSKEY         = os.environ.get("MPESA_PASSKEY", "e9992845c77aa8c47fbe5194c38e0b56f720135017e4f33a29825504bd091c0e")
MPESA_CALLBACK_URL    = os.environ.get("MPESA_CALLBACK_URL", "https://pitch-iq-main.onrender.com")
# TILL (Buy Goods) setup:
#   MPESA_SHORTCODE   = Store / Head Office number (used for the password)
#   MPESA_TILL_NUMBER = the Till number customers pay to
MPESA_TILL_NUMBER     = os.environ.get("MPESA_TILL_NUMBER", "5258013")

# ─── Subscription ─────────────────────────────────────────────────────────────
SUBSCRIPTION_AMOUNT = int(os.environ.get("SUBSCRIPTION_AMOUNT", "50"))
SUBSCRIPTION_DAYS   = int(os.environ.get("SUBSCRIPTION_DAYS", "1"))

# ─── Database ─────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "pitchiq.db")

# ─── Scheduler ────────────────────────────────────────────────────────────────
SCHEDULE_TIME_UTC = os.environ.get("SCHEDULE_TIME_UTC", "07:00")

# ─── Analysis lines ───────────────────────────────────────────────────────────
GOALS_LINE   = 2.5
CORNERS_LINE = 9.5

