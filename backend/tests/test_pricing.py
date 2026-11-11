import unittest
from datetime import date
from decimal import Decimal as D

from app.pricing import calculate_quote


class PricingTests(unittest.TestCase):
    day = date(2026, 11, 11)

    def test_commission_and_currency_markup(self):
        quote = calculate_quote(D('100'), D('95'), self.day, self.day)
        self.assertEqual(quote.total_eur, D('120.00'))
        self.assertEqual(quote.total_rub, D('11970.00'))

    def test_rounding(self):
        quote = calculate_quote(D('19.99'), D('95.1234'), self.day, self.day)
        self.assertEqual(quote.total_eur, D('23.99'))
        self.assertEqual(quote.total_rub, D('2396.11'))

    def test_stale_rate_rejected(self):
        with self.assertRaises(ValueError):
            calculate_quote(D('100'), D('95'), date(2026, 11, 10), self.day)

    def test_invalid_amounts_rejected(self):
        for amount, rate in [('NaN', '95'), ('-1', '95'), ('1', '0'), ('1', 'Infinity')]:
            with self.subTest(amount=amount, rate=rate), self.assertRaises(ValueError):
                calculate_quote(D(amount), D(rate), self.day, self.day)
