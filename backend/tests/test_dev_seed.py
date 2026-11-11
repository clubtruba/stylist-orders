import pytest

from app.auth.telegram import validate_init_data
from app.dev_seed import signed_init_data


def test_development_seed_generates_valid_telegram_signature():
    token = "local-test-token"
    raw = signed_init_data(123, "Local", "local", token)
    identity = validate_init_data(raw, token, 3600)
    assert identity.telegram_user_id == 123


def test_development_signature_fails_with_other_token():
    raw = signed_init_data(123, "Local", "local", "correct-token")
    with pytest.raises(ValueError):
        validate_init_data(raw, "wrong-token", 3600)
