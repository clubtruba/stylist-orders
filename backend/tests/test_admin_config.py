import pytest

from app.core.config import Settings


def test_admin_ids_are_parsed_as_integer_allowlist():
    settings = Settings(telegram_admin_ids="252246696, 123")
    assert settings.telegram_admin_id_set == {252246696, 123}


def test_invalid_admin_id_configuration_is_rejected():
    settings = Settings(telegram_admin_ids="not-an-id")
    with pytest.raises(ValueError):
        _ = settings.telegram_admin_id_set


def test_production_webapp_requires_https():
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            app_secret="a" * 32,
            telegram_webapp_url="http://orders.example.test",
        )


def test_production_webapp_accepts_https():
    settings = Settings(
        app_env="production",
        app_secret="a" * 32,
        telegram_webapp_url="https://orders.papamio.es",
    )
    assert settings.telegram_webapp_url == "https://orders.papamio.es"
