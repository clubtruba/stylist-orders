"""Payment snapshot rules independent of Telegram and persistence."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.money import allocate_proportional, quantize_money


@dataclass(frozen=True)
class PaidQuote:
    quote_id: str
    paid_at: datetime
    total_rub: Decimal
    allocations: tuple[tuple[str, Decimal], ...]

    def refund_amount(self, item_ids: set[str]) -> Decimal:
        allocated = dict(self.allocations)
        if not item_ids <= allocated.keys():
            raise ValueError('Refund contains items outside this payment')
        return sum((allocated[item_id] for item_id in item_ids), Decimal('0.00'))


def confirm_quote(
    quote_id: str,
    quoted_total_rub: Decimal,
    quoted_item_values: dict[str, Decimal],
    screenshot_at: datetime,
) -> PaidQuote:
    """Freeze the issued amount; never request a rate on the screenshot date.

    Call inside the receipt transaction after checking ownership, quote state,
    and Telegram message idempotency. This function does not persist a payment.
    """
    if not quote_id or screenshot_at.utcoffset() is None:
        raise ValueError('Quote ID and timezone-aware screenshot timestamp are required')
    if not quoted_total_rub.is_finite() or quoted_total_rub <= 0:
        raise ValueError('Quoted total must be finite and positive')
    if not quoted_item_values or any(
        not value.is_finite() or value <= 0 for value in quoted_item_values.values()
    ):
        raise ValueError('Quoted item values must be finite and positive')
    total = quantize_money(quoted_total_rub)
    if total != quoted_total_rub:
        raise ValueError('Issued amount must already be rounded to kopecks')
    allocations = allocate_proportional(total, quoted_item_values)
    return PaidQuote(quote_id, screenshot_at, total, tuple(allocations.items()))
