from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


class AllocationError(ValueError):
    pass


def quantize_money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def allocate_equal(total: Decimal, item_ids: list[str]) -> dict[str, Decimal]:
    if total < 0:
        raise AllocationError("total cannot be negative")
    if not item_ids or len(set(item_ids)) != len(item_ids):
        raise AllocationError("unique item ids are required")
    normalized = quantize_money(total)
    base = (normalized / len(item_ids)).quantize(CENT, rounding=ROUND_HALF_UP)
    allocations = {item_id: base for item_id in item_ids}
    remainder_cents = int((normalized - sum(allocations.values())) / CENT)
    step = CENT if remainder_cents > 0 else -CENT
    for item_id in item_ids[: abs(remainder_cents)]:
        allocations[item_id] += step
    if sum(allocations.values()) != normalized:
        raise AllocationError("allocation invariant failed")
    return allocations


def allocate_proportional(total: Decimal, values: dict[str, Decimal]) -> dict[str, Decimal]:
    if total < 0 or not values or any(value < 0 for value in values.values()):
        raise AllocationError("non-negative total and item values are required")
    value_total = sum(values.values())
    if value_total <= 0:
        raise AllocationError("item value total must be positive")
    normalized = quantize_money(total)
    exact = {key: normalized * value / value_total for key, value in values.items()}
    allocated = {key: amount.quantize(CENT, rounding=ROUND_HALF_UP) for key, amount in exact.items()}
    difference_cents = int((normalized - sum(allocated.values())) / CENT)
    if difference_cents:
        ordered = sorted(
            values,
            key=lambda key: exact[key] - allocated[key],
            reverse=difference_cents > 0,
        )
        step = CENT if difference_cents > 0 else -CENT
        for key in ordered[: abs(difference_cents)]:
            allocated[key] += step
    if sum(allocated.values()) != normalized:
        raise AllocationError("allocation invariant failed")
    return allocated
