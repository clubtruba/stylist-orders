import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.auth.telegram import TelegramAuthError, validate_init_data

TOKEN = "123456:test-token"
NOW = 1_800_000_000


def signed_init_data(*, auth_date: int = NOW, user_id: int = 42) -> str:
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAExample",
        "user": json.dumps(
            {"id": user_id, "first_name": "Natalia", "username": "natalia"},
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_init_data_returns_trusted_identity():
    identity = validate_init_data(signed_init_data(), TOKEN, 3600, now=NOW)
    assert identity.telegram_user_id == 42
    assert identity.first_name == "Natalia"


def test_tampered_init_data_is_rejected():
    raw = signed_init_data().replace("Natalia", "Olga")
    with pytest.raises(TelegramAuthError, match="signature"):
        validate_init_data(raw, TOKEN, 3600, now=NOW)


def test_expired_init_data_is_rejected():
    with pytest.raises(TelegramAuthError, match="expired"):
        validate_init_data(signed_init_data(auth_date=NOW - 3601), TOKEN, 3600, now=NOW)


def test_future_init_data_is_rejected():
    with pytest.raises(TelegramAuthError, match="future"):
        validate_init_data(signed_init_data(auth_date=NOW + 31), TOKEN, 3600, now=NOW)
