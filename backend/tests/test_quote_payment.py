import unittest
from datetime import datetime, timezone
from decimal import Decimal as D

from app.domain.quote_payment import confirm_quote


class QuotePaymentTests(unittest.TestCase):
    def test_later_screenshot_preserves_issued_amount(self):
        paid = confirm_quote('quote-1', D('11970.00'), {'item-1': D('100')},
                             datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertEqual(paid.total_rub, D('11970.00'))
        self.assertEqual(paid.refund_amount({'item-1'}), D('11970.00'))

    def test_refunds_preserve_total_to_kopeck(self):
        paid = confirm_quote('quote-2', D('100.00'),
                             {'a': D('1'), 'b': D('1'), 'c': D('1')},
                             datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertEqual(paid.refund_amount({'a', 'b', 'c'}), D('100.00'))
        self.assertEqual(sum(dict(paid.allocations).values()), paid.total_rub)
        with self.assertRaises(ValueError):
            paid.refund_amount({'unpaid-item'})

    def test_invalid_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            confirm_quote('quote-3', D('100.001'), {'a': D('1')},
                          datetime(2026, 11, 12, tzinfo=timezone.utc))
