"""
football_bot/mpesa.py
======================
Safaricom Daraja API - M-Pesa Express (STK Push)
Handles: access token, STK push, payment verification
"""

import requests
import base64
import logging
from datetime import datetime
from config import (
    MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET,
    MPESA_SHORTCODE, MPESA_PASSKEY,
    MPESA_CALLBACK_URL, MPESA_ENV,
    SUBSCRIPTION_AMOUNT,
)

logger = logging.getLogger(__name__)

SANDBOX_BASE    = "https://sandbox.safaricom.co.ke"
PRODUCTION_BASE = "https://api.safaricom.co.ke"
BASE = SANDBOX_BASE if MPESA_ENV == "sandbox" else PRODUCTION_BASE


def get_access_token() -> str:
    url = f"{BASE}/oauth/v1/generate?grant_type=client_credentials"
    try:
        r = requests.get(url, auth=(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET), timeout=15)
        r.raise_for_status()
        return r.json().get("access_token", "")
    except Exception as e:
        logger.error(f"M-Pesa token error: {e}")
        return ""


def _password_and_timestamp() -> tuple[str, str]:
    ts  = datetime.now().strftime("%Y%m%d%H%M%S")
    raw = f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{ts}"
    pwd = base64.b64encode(raw.encode()).decode()
    return pwd, ts


def format_phone(phone: str) -> str:
    """Normalise to 2547XXXXXXXX."""
    phone = phone.strip().replace(" ", "").replace("-", "").replace("+", "")
    if phone.startswith("07") or phone.startswith("01"):
        phone = "254" + phone[1:]
    if phone.startswith("7") or phone.startswith("1"):
        phone = "254" + phone
    return phone


def stk_push(phone: str, user_id: int) -> dict:
    """Trigger STK push. Returns {success, checkout_request_id} or {success:False, error}."""
    token = get_access_token()
    if not token:
        return {"success": False, "error": "Could not get M-Pesa token"}

    pwd, ts = _password_and_timestamp()
    phone   = format_phone(phone)

    payload = {
        "BusinessShortCode": MPESA_SHORTCODE,
        "Password":          pwd,
        "Timestamp":         ts,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            SUBSCRIPTION_AMOUNT,
        "PartyA":            phone,
        "PartyB":            MPESA_SHORTCODE,
        "PhoneNumber":       phone,
        "CallBackURL":       MPESA_CALLBACK_URL,
        "AccountReference":  f"PitchIQ-{user_id}",
        "TransactionDesc":   "PitchIQ Daily VIP Predictions",
    }

    try:
        r = requests.post(
            f"{BASE}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
        data = r.json()
        logger.info(f"STK push → {data}")
        if data.get("ResponseCode") == "0":
            return {"success": True, "checkout_request_id": data["CheckoutRequestID"]}
        return {"success": False, "error": data.get("errorMessage", data.get("ResponseDescription", "Error"))}
    except Exception as e:
        logger.error(f"STK push error: {e}")
        return {"success": False, "error": str(e)}


def query_payment(checkout_request_id: str) -> dict:
    """Poll payment status. Returns {paid: True/False, reason}."""
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
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        data = r.json()
        rc   = str(data.get("ResultCode", "-1"))
        if rc == "0":
            return {"paid": True,  "reason": "success"}
        elif rc == "1032":
            return {"paid": False, "reason": "cancelled"}
        elif rc == "1037":
            return {"paid": False, "reason": "timeout"}
        else:
            return {"paid": False, "reason": data.get("ResultDesc", "failed")}
    except Exception as e:
        logger.error(f"STK query error: {e}")
        return {"paid": False, "reason": str(e)}