from app.models.item import ItemStatus


class InvalidItemTransition(ValueError):
    pass


ALLOWED_ITEM_TRANSITIONS: dict[ItemStatus, frozenset[ItemStatus]] = {
    ItemStatus.TO_BUY: frozenset(
        {ItemStatus.ORDERED, ItemStatus.PURCHASED_OFFLINE, ItemStatus.CANCELLED}
    ),
    ItemStatus.ORDERED: frozenset(
        {ItemStatus.ON_THE_WAY_TO_US, ItemStatus.READY_FOR_PICKUP, ItemStatus.CANCELLED}
    ),
    ItemStatus.PURCHASED_OFFLINE: frozenset({ItemStatus.RECEIVED, ItemStatus.RETURN_IN_PROGRESS}),
    ItemStatus.ON_THE_WAY_TO_US: frozenset(
        {ItemStatus.READY_FOR_PICKUP, ItemStatus.RECEIVED, ItemStatus.RETURN_IN_PROGRESS}
    ),
    ItemStatus.READY_FOR_PICKUP: frozenset({ItemStatus.RECEIVED, ItemStatus.RETURN_IN_PROGRESS}),
    ItemStatus.RECEIVED: frozenset(
        {ItemStatus.ASSIGNED_TO_SHIPMENT, ItemStatus.RETURN_IN_PROGRESS}
    ),
    ItemStatus.ASSIGNED_TO_SHIPMENT: frozenset({ItemStatus.RECEIVED, ItemStatus.SHIPPED}),
    ItemStatus.SHIPPED: frozenset({ItemStatus.DELIVERED}),
    ItemStatus.RETURN_IN_PROGRESS: frozenset({ItemStatus.RETURNED, ItemStatus.RECEIVED}),
    ItemStatus.DELIVERED: frozenset(),
    ItemStatus.CANCELLED: frozenset(),
    ItemStatus.RETURNED: frozenset(),
}


def ensure_item_transition(current: ItemStatus, target: ItemStatus) -> None:
    if target not in ALLOWED_ITEM_TRANSITIONS[current]:
        raise InvalidItemTransition(f"item cannot transition from {current.value} to {target.value}")
