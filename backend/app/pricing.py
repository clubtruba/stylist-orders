"""Pure pricing rules; transport and exchange-rate retrieval are separate."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


CENT = Decimal('0.01')


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Quote:
    goods_eur: Decimal
    total_eur: Decimal
    eur_rub_rate: Decimal
    total_rub: Decimal
    rate_date: date


def calculate_quote(
    goods_eur: Decimal, eur_rub_rate: Decimal, rate_date: date, required_date: date
) -> Quote:
    """Use an explicitly supplied date so server timezone cannot alter pricing."""
    if not goods_eur.is_finite() or goods_eur < 0:
        raise ValueError('Goods amount must be finite and nonnegative')
    if not eur_rub_rate.is_finite() or eur_rub_rate <= 0:
        raise ValueError('Exchange rate must be finite and positive')
    if rate_date != required_date:
        raise ValueError('An exchange rate for the requested date is required')
    goods = money(goods_eur)
    total_eur = money(goods * Decimal('1.20'))
    total_rub = money(total_eur * eur_rub_rate * Decimal('1.05'))
    return Quote(goods, total_eur, eur_rub_rate, total_rub, rate_date)
