import pytest
from pydantic import ValidationError

from app.schemas.catalog import CustomerProfileUpdateRequest, ItemStatusCorrectionRequest


def test_profile_normalizes_country_code():
    profile = CustomerProfileUpdateRequest(
        display_name="Иванов Иван Иванович",
        phone="+372 5555 0000",
        country_code="ee",
        postal_code="10111",
        city="Tallinn",
        address_line1="Test street 1",
    )
    assert profile.country_code == "EE"


def test_status_correction_requires_reason():
    with pytest.raises(ValidationError):
        ItemStatusCorrectionRequest(status="RECEIVED", reason="")
