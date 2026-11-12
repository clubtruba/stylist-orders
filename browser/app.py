"""Internal Zara reader. No database, Telegram credentials or public port."""

import asyncio
from decimal import Decimal, InvalidOperation

from app.services.product_import import identify_product
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
lock = asyncio.Lock()
PRICE = '.product-detail-info__price [data-qa-id="price-container-current"] data'


class Command(BaseModel):
    url: str = Field(max_length=3000)


def price_result(name, values):
    """Only the unique current EUR price of the primary product is acceptable."""
    name = name.strip()[:500] if isinstance(name, str) else None
    if len(values) != 1 or values[0].get("currency") != "EUR":
        return dict(name=name, price_eur=None, manual_reason="price_ambiguous")
    try:
        price = Decimal(values[0]["value"])
        if (
            not price.is_finite()
            or price <= 0
            or price > Decimal("10000000")
            or price != price.quantize(Decimal(".01"))
        ):
            raise ValueError("invalid price")
    except (InvalidOperation, ValueError, KeyError, TypeError):
        return dict(name=name, price_eur=None, manual_reason="price_invalid")
    return dict(name=name, price_eur=str(price), manual_reason=None)


async def fetch_product(product):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        try:
            context = await browser.new_context(
                locale="en-GB", viewport={"width": 1280, "height": 900}
            )
            page = await context.new_page()

            async def restrict_navigation(route):
                request = route.request
                if request.is_navigation_request() and request.frame == page.main_frame:
                    # Permit only the Spanish home page and the requested product.
                    from urllib.parse import urlsplit

                    url = urlsplit(request.url)
                    allowed = (
                        url.scheme == "https"
                        and url.hostname in ("www.zara.com", "zara.com")
                        and url.port in (None, 443)
                    )
                    if allowed and url.path not in ("/es/en/", "/es/es/"):
                        try:
                            allowed = (
                                identify_product(request.url).product_id
                                == product.product_id
                            )
                        except ValueError:
                            allowed = False
                    if not allowed:
                        await route.abort()
                        return
                if request.resource_type in ("image", "media", "font"):
                    await route.abort()
                    return
                await route.continue_()

            await page.route("**/*", restrict_navigation)
            home = await page.goto(
                "https://www.zara.com/es/en/",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            if not home or home.status != 200:
                return dict(name=None, price_eur=None, manual_reason="home_unavailable")
            # Let normal browser scripts establish the session before navigation.
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            response = await page.goto(
                product.url, wait_until="domcontentloaded", timeout=20000
            )
            if not response or response.status != 200:
                return dict(
                    name=None,
                    price_eur=None,
                    manual_reason=f"http_{response.status if response else 'missing'}",
                )
            final = identify_product(page.url)
            if final.product_id != product.product_id:
                return dict(name=None, price_eur=None, manual_reason="wrong_product")
            await page.locator(PRICE).first.wait_for(state="attached", timeout=10000)
            name = await page.locator("h1.product-detail-info__header-name").inner_text(
                timeout=3000
            )
            values = await page.locator(PRICE).evaluate_all(
                '(nodes)=>nodes.map(n=>({value:n.getAttribute("value"),currency:n.getAttribute("data-currency")}))'
            )
            return price_result(name, values)
        finally:
            await browser.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "product-browser"}


@app.post("/product")
async def read_product(command: Command):
    try:
        product = identify_product(command.url)
        if product.merchant != "Zara":
            raise ValueError("unsupported")
    except ValueError as exc:
        raise HTTPException(
            422, "Only Spanish Zara product links are supported"
        ) from exc
    if lock.locked():
        return dict(name=None, price_eur=None, manual_reason="browser_busy")
    async with lock:
        try:
            async with asyncio.timeout(55):
                result = await fetch_product(product)
        except TimeoutError:
            result = dict(name=None, price_eur=None, manual_reason="browser_timeout")
        except Exception:
            result = dict(
                name=None, price_eur=None, manual_reason="browser_unavailable"
            )
    return {**result, "product_id": product.product_id}
