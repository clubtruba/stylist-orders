import json
import unittest
from decimal import Decimal

from app.services.product_import import identify_product, product_metadata


class ProductImportTests(unittest.TestCase):
    def test_spanish_products(self):
        self.assertEqual(identify_product('https://www2.hm.com/es_es/productpage.1352121001.html').product_id, '1352121001')
        self.assertEqual(identify_product('https://www.zara.com/es/en/basic-plush-trousers-p03199635.html?v1=594401162&v2=2419265').product_id, '03199635')

    def test_reject_non_product_and_untrusted_links(self):
        for url in ('http://www.zara.com/es/en/x-p123.html', 'https://www.zara.com.evil.test/es/en/x-p123.html', 'https://127.0.0.1/a', 'https://www2.hm.com/en_us/productpage.123.html', 'https://user@www.zara.com/es/en/x-p123.html'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                identify_product(url)

    def metadata(self, offers):
        return product_metadata('<script type="application/ld+json">' + json.dumps({'@type':'Product', 'name':'Example', 'offers':offers}) + '</script>')

    def test_eur_offer(self):
        self.assertEqual(self.metadata({'price':'29.99','priceCurrency':'EUR'}), ('Example', Decimal('29.99')))

    def test_ambiguous_or_foreign_prices_require_manual_input(self):
        for offers in ([{'price':'10','priceCurrency':'EUR'}, {'price':'20','priceCurrency':'EUR'}], {'price':'20','priceCurrency':'USD'}, {'price':'NaN','priceCurrency':'EUR'}, {'lowPrice':'10','highPrice':'20','priceCurrency':'EUR'}):
            self.assertIsNone(self.metadata(offers)[1])

    def test_block_page_is_not_a_product(self):
        self.assertEqual(product_metadata('<h1>Access denied</h1>'), (None, None))
