"""
football_bot/mpesa.py
======================
Safaricom Daraja - M-Pesa Express (STK Push) for a TILL number (Buy Goods).

Till rules:
  BusinessShortCode = Store / Head Office number  (MPESA_SHORTCODE)
  PartyB            = Till number                 (MPESA_TILL_NUMBER)
  TransactionType   = CustomerBuyGoodsOnline
  Password          = base64(BusinessShortCode + Passkey + Timestamp)
"""

import base64
import logging
import re
import time
from datetime import datetime

import pytz
import requests

from config import (
    MPESA_ENV, MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET,
    MPESA_SHORTCODE, MPESA_TILL_NUMBER, MPESA_PASSKEY,
    MPESA_CALLBACK_URL, SUBSCRIPTION_AMOUNT,
)

logger = logging.getLogger(__name__)

BASE = (
    "https://sandbox.safaricom.co.ke"
    if MPESA_ENV == "sandbox"
    else "https://api.safaricom.co.ke"
)

# Sandbox only supports the paybill flow with the test shortcode
TXN_TYPE = "CustomerPayBillOnline" if MPESA_ENV == "sandbox" else "CustomerBuyGoodsOnline"
PARTY_B  = MPESA_SHORTCODE if MPESA_ENV == "sandbox" else MPESA_TILL_NUMBER

_NAIROBI = pytz.timezone("Africa/Nairobi")
_token_cache = {"token": "", "expires": 0.0}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_access_token() -> str:
    """OAuth token, cached for ~55 minutes."""
    if _token_cache["token"] and time.time() < _token_cache["expires"]:
        return _token_cache["token"]
    try:
        r = requests.get(
            f"{BASE}/oauth/v1/generate?grant_type=client_credentials",
            auth=(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET),
            timeout=15,
        )
        r.raise_for_status()
        token = r.json().get("access_token", "")
        if token:
            _token_cache["token"]   = token
            _token_cache["expires"] = time.time() + 55 * 60
        return token
    except Exception as e:
        logger.error(f"M-Pesa token error: {e}")
        return ""


def _password_and_timestamp() -> tuple[str, str]:
    ts  = datetime.now(_NAIROBI).strftime("%Y%m%d%H%M%S")
    raw = f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{ts}"
    return base64.b64encode(raw.encode()).decode(), ts


def format_phone(phone: str) -> str:
    """Normalise to 2547XXXXXXXX / 2541XXXXXXXX."""
    p = re.sub(r"\D", "", phone)          # keep digits only
    if p.startswith("0"):
        p = "254" + p[1:]
    elif p.startswith(("7", "1")) and len(p) == 9:
        p = "254" + p
    return p


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ─── STK Push ────────────────────────────────────────────────────────────────

def stk_push(phone: str, user_id: int) -> dict:
    """Returns {success, checkout_request_id} or {success: False, error}."""
    token = get_access_token()
    if not token:
        return {"success": False, "error": "Could not get M-Pesa token (check consumer key/secret and MPESA_ENV)"}

    pwd, ts = _password_and_timestamp()
    phone   = format_phone(phone)

    payload = {
        "BusinessShortCode": MPESA_SHORTCODE,
        "Password":          pwd,
        "Timestamp":         ts,
        "TransactionType":   TXN_TYPE,
        "Amount":            int(SUBSCRIPTION_AMOUNT),
        "PartyA":            phone,
        "PartyB":            PARTY_B,
        "PhoneNumber":       phone,
        "CallBackURL":       MPESA_CALLBACK_URL,
        "AccountReference":  "PitchIQ",        # max 12 chars
        "TransactionDesc":   "PitchIQ VIP",    # max 13 chars
    }

    try:
        r    = requests.post(f"{BASE}/mpesa/stkpush/v1/processrequest",
                             json=payload, headers=_headers(token), timeout=30)
        data = r.json()
        logger.info(f"STK push → HTTP {r.status_code} {data}")

        if str(data.get("ResponseCode")) == "0":
            return {"success": True, "checkout_request_id": data["CheckoutRequestID"]}

        return {
            "success": False,
            "error": data.get("errorMessage")
                     or data.get("ResponseDescription")
                     or f"HTTP {r.status_code}",
        }
    except Exception as e:
        logger.error(f"STK push error: {e}")
        return {"success": False, "error": str(e)}


# ─── Payment status query ────────────────────────────────────────────────────

def query_payment(checkout_request_id: str) -> dict:
    """Returns {paid: bool, reason: str}. reason: success|cancelled|timeout|pending|<desc>"""
    token = get_access_token()
    if not token:
        return {"paid": False, "reason": "token_error"}

    pwd, ts = _password_and_timestamp()
    try:
        r = requests.post(
            f"{BASE}/mpesa/stkpushquery/v1/query",
            json={
                "BusinessShortCode": MPESA_SHORTCODE,
                "Password":          pwd,
                "Timestamp":         ts,
                "CheckoutRequestID": checkout_request_id,
            },
            headers=_headers(token),
            timeout=15,
        )
        data = r.json()
        logger.info(f"STK query → HTTP {r.status_code} {data}")

        # No ResultCode = still being processed (customer on PIN screen) or rate-limited
        if "ResultCode" not in data:
            return {"paid": False, "reason": "pending"}

        rc = str(data["ResultCode"])
        if rc == "0":
            return {"paid": True,  "reason": "success"}
        if rc == "1032":
            return {"paid": False, "reason": "cancelled"}
        if rc == "1037":
            return {"paid": False, "reason": "timeout"}
        if rc == "1":
            return {"paid": False, "reason": "insufficient funds"}
        if rc == "2001":
            return {"paid": False, "reason": "wrong PIN"}
        return {"paid": False, "reason": data.get("ResultDesc", "failed")}
    except Exception as e:
        logger.error(f"STK query error: {e}")
        return {"paid": False, "reason": str(e)}
