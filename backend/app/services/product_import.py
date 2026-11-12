"""Conservative product metadata import: ambiguous prices require manual input."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ProductLink:
    url: str
    merchant: str
    product_id: str


def identify_product(url: str) -> ProductLink:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("Use an HTTPS product link")
    if parts.hostname in ("www2.hm.com", "www.hm.com"):
        match = re.fullmatch(r"/es_es/productpage\.(\d+)\.html", parts.path)
        merchant = "H&M"
    elif parts.hostname in ("www.zara.com", "zara.com"):
        match = re.fullmatch(r"/es/(?:es|en)/[^/]+-p(\d+)\.html", parts.path)
        merchant = "Zara"
    else:
        raise ValueError("Unsupported store")
    if not match:
        raise ValueError("Use a Spanish product page")
    return ProductLink(url, merchant, match.group(1))


class StructuredDataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            try:
                self.blocks.append(json.loads("".join(self.current)))
            except (ValueError, TypeError):
                pass
            self.current = None


def product_metadata(html: str) -> tuple[str | None, Decimal | None]:
    """Read only one unambiguous Product and its EUR Offer, never recommendations."""
    parser = StructuredDataParser()
    parser.feed(html)
    products = []

    def visit(node):
        if isinstance(node, list):
            for value in node:
                visit(value)
        elif isinstance(node, dict):
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if "Product" in types:
                products.append(node)
            elif "@graph" in node:
                visit(node["@graph"])

    visit(parser.blocks)
    if len(products) != 1:
        return None, None
    product = products[0]
    name = product.get("name")
    name = name.strip() if isinstance(name, str) and name.strip() else None
    offers = product.get("offers", [])
    if isinstance(offers, dict):
        offers = [offers]
    prices = set()
    if not isinstance(offers, list):
        return name, None
    for offer in offers:
        if not isinstance(offer, dict) or offer.get("priceCurrency") != "EUR":
            return name, None
        try:
            price = Decimal(str(offer["price"]))
            if not price.is_finite() or price <= 0 or price != price.quantize(Decimal(".01")):
                return name, None
            prices.add(price)
        except (KeyError, InvalidOperation, ValueError):
            return name, None
    return name, next(iter(prices)) if len(prices) == 1 else None


@dataclass(frozen=True)
class ImportResult:
    product: ProductLink
    name: str | None = None
    price_eur: Decimal | None = None
    manual_reason: str | None = None
    source: str = "structured_data"


async def import_product(url: str) -> ImportResult:
    import httpx

    product = identify_product(url)
    from app.core.config import get_settings

    browser_url = get_settings().product_browser_url
    if product.merchant == "Zara" and browser_url:
        return await import_from_browser(product, browser_url)
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                "GET", product.url, headers={"Accept": "text/html"}
            ) as response:
                if response.status_code != 200:
                    return ImportResult(product, manual_reason=f"http_{response.status_code}")
                if "text/html" not in response.headers.get("content-type", "").lower():
                    return ImportResult(product, manual_reason="unexpected_content")
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 4_000_000:
                        return ImportResult(product, manual_reason="page_too_large")
        name, price = product_metadata(chunks.decode("utf-8", errors="replace"))
        return ImportResult(
            product, name, price, None if price is not None else "price_unavailable"
        )
    except httpx.HTTPError:
        return ImportResult(product, manual_reason="connection_failed")


async def import_from_browser(product: ProductLink, endpoint: str) -> ImportResult:
    import asyncio

    import httpx

    try:
        async with asyncio.timeout(60):
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(58, connect=2), trust_env=False
            ) as client:
                response = await client.post(
                    endpoint.rstrip("/") + "/product", json={"url": product.url}
                )
                response.raise_for_status()
                data = response.json()
        if not isinstance(data, dict):
            raise ValueError("invalid browser response")
        name = data.get("name")
        name = name[:500] if isinstance(name, str) else None
        if data.get("manual_reason") or data.get("product_id") != product.product_id:
            return ImportResult(product, name=name, manual_reason="browser_price_unavailable")
        price = Decimal(str(data["price_eur"]))
        if (
            not price.is_finite()
            or price <= 0
            or price > Decimal("10000000")
            or price != price.quantize(Decimal(".01"))
        ):
            raise ValueError("invalid price")
        return ImportResult(product, name=name, price_eur=price, source="zara_browser")
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, InvalidOperation):
        return ImportResult(product, manual_reason="browser_unavailable")
