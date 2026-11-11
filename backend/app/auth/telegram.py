import hashlib
import hmac
import json
from dataclasses import dataclass
from time import time
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_user_id: int
    first_name: str
    last_name: str | None
    username: str | None
    auth_date: int


def validate_init_data(
    raw_init_data: str,
    bot_token: str,
    max_age_seconds: int,
    now: int | None = None,
) -> TelegramIdentity:
    if not raw_init_data or not bot_token:
        raise TelegramAuthError("Telegram authentication data is unavailable")
    try:
        fields = dict(parse_qsl(raw_init_data, keep_blank_values=True, strict_parsing=True))
        received_hash = fields.pop("hash")
        auth_date = int(fields["auth_date"])
        user = json.loads(fields["user"])
        telegram_user_id = int(user["id"])
        first_name = str(user["first_name"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramAuthError("Malformed Telegram authentication data") from exc

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramAuthError("Invalid Telegram authentication signature")

    current_time = int(time()) if now is None else now
    if auth_date > current_time + 30:
        raise TelegramAuthError("Telegram authentication date is in the future")
    if current_time - auth_date > max_age_seconds:
        raise TelegramAuthError("Telegram authentication data has expired")

    return TelegramIdentity(
        telegram_user_id=telegram_user_id,
        first_name=first_name,
        last_name=str(user["last_name"]) if user.get("last_name") is not None else None,
        username=str(user["username"]) if user.get("username") is not None else None,
        auth_date=auth_date,
    )
