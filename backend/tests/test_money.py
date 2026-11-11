from decimal import Decimal

import pytest

from app.domain.money import AllocationError, allocate_equal, allocate_proportional


def test_equal_allocation_assigns_rounding_remainder_deterministically():
    result = allocate_equal(Decimal("10.00"), ["a", "b", "c"])
    assert result == {"a": Decimal("3.34"), "b": Decimal("3.33"), "c": Decimal("3.33")}
    assert sum(result.values()) == Decimal("10.00")


def test_proportional_allocation_preserves_total():
    result = allocate_proportional(
        Decimal("4.95"), {"dress": Decimal("29.95"), "shirt": Decimal("19.95")}
    )
    assert result == {"dress": Decimal("2.97"), "shirt": Decimal("1.98")}
    assert sum(result.values()) == Decimal("4.95")


def test_allocation_rejects_invalid_input():
    with pytest.raises(AllocationError):
        allocate_equal(Decimal("1.00"), [])
    with pytest.raises(AllocationError):
        allocate_proportional(Decimal("1.00"), {"a": Decimal("0")})
