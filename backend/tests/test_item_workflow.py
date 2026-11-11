import pytest

from app.domain.item_workflow import InvalidItemTransition, ensure_item_transition
from app.models.item import ItemStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ItemStatus.TO_BUY, ItemStatus.ORDERED),
        (ItemStatus.TO_BUY, ItemStatus.PURCHASED_OFFLINE),
        (ItemStatus.ORDERED, ItemStatus.ON_THE_WAY_TO_US),
        (ItemStatus.RECEIVED, ItemStatus.ASSIGNED_TO_SHIPMENT),
        (ItemStatus.ASSIGNED_TO_SHIPMENT, ItemStatus.SHIPPED),
        (ItemStatus.SHIPPED, ItemStatus.DELIVERED),
    ],
)
def test_allowed_transitions(current, target):
    ensure_item_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ItemStatus.TO_BUY, ItemStatus.RECEIVED),
        (ItemStatus.RECEIVED, ItemStatus.SHIPPED),
        (ItemStatus.DELIVERED, ItemStatus.TO_BUY),
        (ItemStatus.CANCELLED, ItemStatus.ORDERED),
    ],
)
def test_forbidden_transitions(current, target):
    with pytest.raises(InvalidItemTransition):
        ensure_item_transition(current, target)
