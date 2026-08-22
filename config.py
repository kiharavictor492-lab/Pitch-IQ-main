"""
football_bot/config.py
=======================
Fill in your credentials below before running.
Only ONE free API key needed (football-data.org).
"""

# ─── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "8257518569:AAH2n2SkoW4f_kelcqokNVM7cb2cL5JOscM"  # From @BotFather
FREE_CHANNEL_ID    = "@PitchIQ_vip"                                        # e.g. @FootballFreeTips
BOT_USERNAME       = "PitchIQ_Bot"                                     # WITHOUT @ e.g. "PitchIQBot"
#VIP_CHANNEL_ID     = "@pitchIQ_vip"                                   # e.g. @FootballVIPTips
ADMIN_CHAT_IDS     = [8225041564]                                      # Your Telegram numeric user ID

# ─── football-data.org (FREE key) ────────────────────────────────────────────
# Free tier covers: PL, BL1, SA, PD, FL1, CL, EL, WC, EC and more
FOOTBALL_DATA_ORG_KEY = "625f3bda19c04ee7a5963d12b9219032"

# ─── Leagues to track (football-data.org competition codes) ──────────────────
# PL=Premier League, BL1=Bundesliga, SA=Serie A, PD=La Liga,
# FL1=Ligue 1, CL=Champions League, EL=Europa League,
# DED=Eredivisie, PPL=Primeira Liga, ELC=Championship
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
# Get these from: https://developer.safaricom.co.ke
MPESA_ENV             = "sandbox"       # Change to "production" when going live
MPESA_CONSUMER_KEY    = "ekix8AVLAE0GPBvKexeDnVFAUbGn7mo5aPiudzKJzHYMp6JH"
MPESA_CONSUMER_SECRET = "W7puYgPb0K2kX6ISndvqIg1hjECGGws5QUSY5GmblMiY3kw9o7cZd2Um8GglfW8v"
MPESA_SHORTCODE       = "174379"        # Sandbox shortcode (replace with yours in production)
MPESA_PASSKEY         = "IvYhxT6rXEdi8/TahVVYRBTII3QihXkd8cVI3s2xSUeWXd6V7R+09T/NEF93orlwM9nVw3C4HLrU1ZSkSu+E+ofA820U9AVSyVLyB3zishorDlsdiEaAR+heHLg4V/Wl21OT/x5aOZYHxjXSgCI7B9ReMbalJ4VUnENzII5qUuesnJMHtzLRbPPzO3puK5GVEt466su/3rVJNxCKVlRsYBuCeNCfeYdmR2Hu7q0MpmhyD/QRpNWa3izpfdQ0IX7fjF6kN/MwpstzHYdxHNH09HIFo9nJFr43O9SvA8BkxA5rGREQwl7CYwg/BmanW+++2XzmN4939u5cBXsY40JPfA=="
MPESA_CALLBACK_URL    = "https://pitch-iq-main-production.up.railway.app"  # Must be public HTTPS URL

#3BL3PG7NwRh5WJlRZbzuD2xRkfB_3DWr1uFBrz7C2ZMyHNQC4
#covCWSv+5/Sej6ODoZ+N3D6nLSQyjFUhjsDK8exoohQ5VixQ7YLnQr4NQmgRvXsX5Co+ZdSyRjDmc7UZbcG9oV3jCjFlJsXGWw/8yr+hjnuW4G/aofCPO4+HfXkzzzM7YRiVUwo2wVVKS/GHcCNvDflmqf1zMBBWtPR/6lCYwAoi8dHP9ax/j4pR2SktVN0D6QtTUMM3/mjo3FRG3L13FM07VozAV9nTD+WUpgK5109TtHoBDKLvgCLX9rDvhkWE12+UHBIjVbEbdoFggxqkAkG/OO8XaUSrAZaEGSih893LwMS+OPHzyX4J9A7v6Nu83ykwNd102eF6f9dQOKO8mg==

 
# ─── Subscription ─────────────────────────────────────────────────────────────
SUBSCRIPTION_AMOUNT = 50       # KSh 50 per day
SUBSCRIPTION_DAYS   = 1        # How many days one payment unlocks
 
# ─── Database ─────────────────────────────────────────────────────────────────
DB_PATH = "pitchiq.db"         # SQLite file — auto-created on first run

# ─── API Rate Limiting ────────────────────────────────────────────────────────
# football-data.org free tier = 10 requests/minute
# Set to 6 seconds to stay safely under the limit
# Increase to 10+ if you still get 429 errors
API_DELAY_SECONDS = 6
 

# ─── Scheduler ───────────────────────────────────────────────────────────────
SCHEDULE_TIME_UTC = "07:00"   # Daily post time in UTC

# ─── Analysis lines ──────────────────────────────────────────────────────────
GOALS_LINE   = 2.5
CORNERS_LINE = 9.5
