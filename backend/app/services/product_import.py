"""Conservative product metadata import: ambiguous prices require manual input."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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
    variants: tuple[dict, ...] = ()


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
        return ImportResult(
            product, name=name, price_eur=price, source="zara_browser",
            variants=validate_variants(data.get("variants"), product),
        )
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, InvalidOperation):
        return ImportResult(product, manual_reason="browser_unavailable")


def _label(value, maximum):
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value if value and len(value) <= maximum else None


def _amount(value):
    try:
        price = Decimal(str(value))
        if price.is_finite() and 0 < price <= 10_000_000 and price == price.quantize(Decimal(".01")):
            return str(price)
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def validate_variants(raw, product):
    """Bound external metadata and never accept a different store or product URL."""
    if not isinstance(raw, list) or len(raw) > 50:
        return ()
    result = []
    for color in raw:
        if not isinstance(color, dict):
            continue
        name = _label(color.get("name"), 128)
        url = color.get("url")
        try:
            link = identify_product(url) if isinstance(url, str) and len(url) <= 3000 else None
        except ValueError:
            continue
        if not name or not link or link.merchant != product.merchant or link.product_id != product.product_id:
            continue
        sizes = color.get("sizes")
        if not isinstance(sizes, list) or len(sizes) > 80:
            continue
        clean_sizes = []
        for size in sizes:
            if not isinstance(size, dict):
                continue
            label = _label(size.get("name"), 64)
            if label and not any(s["name"] == label for s in clean_sizes):
                clean_sizes.append({"name": label, "price_eur": _amount(size.get("price_eur"))})
        result.append({
            "name": name, "url": url, "price_eur": _amount(color.get("price_eur")),
            "sizes": clean_sizes,
        })
    return tuple(result)


def zara_variants(html, product):
    """Read the primary product's JSON payload without executing page scripts."""
    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inside = False
            self.blocks = []

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.inside = True

        def handle_endtag(self, tag):
            if tag == "script":
                self.inside = False

        def handle_data(self, data):
            if self.inside and "zara.viewPayload" in data:
                self.blocks.append(data)

    if not isinstance(html, str) or len(html) > 8_000_000:
        return ()
    parser = Scripts()
    parser.feed(html)
    for block in parser.blocks:
        match = re.search(r"(?:window\.)?zara\.viewPayload\s*=\s*", block)
        if not match:
            continue
        try:
            payload = json.JSONDecoder().raw_decode(block[match.end():])[0]
            item = payload["product"]
            if str(item["seo"]["seoProductId"]) != product.product_id:
                continue
            colors = item["detail"]["colors"]
            if not isinstance(colors, list) or len(colors) > 50:
                continue
            variants = []
            for color in colors:
                if not isinstance(color, dict):
                    continue
                variant_id = str(color.get("productId", ""))
                if not re.fullmatch(r"[0-9]{1,20}", variant_id):
                    continue
                parts = urlsplit(product.url)
                query = [(k, v) for k, v in parse_qsl(parts.query) if k != "v1"]
                query.append(("v1", variant_id))
                url = urlunsplit(parts._replace(query=urlencode(query)))

                def euros(value):
                    return str(Decimal(value) / 100) if type(value) is int and value > 0 else None

                sizes = color.get("sizes")
                if not isinstance(sizes, list) or len(sizes) > 80:
                    continue
                variants.append({
                    "name": color.get("name"), "url": url,
                    "price_eur": euros(color.get("price")),
                    "sizes": [
                        {"name": size.get("name"), "price_eur": euros(size.get("price", color.get("price")))}
                        for size in sizes
                        if isinstance(size, dict) and size.get("availability") == "in_stock"
                    ],
                })
            return validate_variants(variants, product)
        except (ValueError, KeyError, TypeError, InvalidOperation):
            continue
    return ()
