from unittest.mock import AsyncMock

import httpx
import pytest
from browser import app as worker
from httpx import ASGITransport, AsyncClient

from app.services import product_import as importer

URL = "https://www.zara.com/es/en/combined-satin-trousers-p08912573.html?v1=594839492"


@pytest.mark.parametrize(
    "values",
    [
        [],
        [{"value": "10", "currency": "USD"}],
        [{"value": "NaN", "currency": "EUR"}],
        [{"value": "0", "currency": "EUR"}],
        [{"value": "10", "currency": "EUR"}, {"value": "20", "currency": "EUR"}],
    ],
)
def test_ambiguous_browser_price_requires_manual_input(values):
    assert worker.price_result("Example", values)["price_eur"] is None


def test_browser_price_accepts_only_current_eur_amount():
    assert worker.price_result(" Trousers ", [{"value": "35.95", "currency": "EUR"}]) == dict(
        name="Trousers", price_eur="35.95", manual_reason=None
    )


@pytest.mark.asyncio
async def test_worker_rejects_untrusted_and_wrong_store_links():
    async with AsyncClient(
        transport=ASGITransport(app=worker.app), base_url="http://test"
    ) as client:
        for url in [
            "http://127.0.0.1/a",
            "https://www.zara.com.evil.test/es/en/x-p123.html",
            "https://www2.hm.com/es_es/productpage.1352121001.html",
        ]:
            assert (await client.post("/product", json={"url": url})).status_code == 422


@pytest.mark.asyncio
async def test_worker_browser_error_and_busy_are_manual_fallback(monkeypatch):
    monkeypatch.setattr(
        worker, "fetch_product", AsyncMock(side_effect=RuntimeError("browser crashed"))
    )
    async with AsyncClient(
        transport=ASGITransport(app=worker.app), base_url="http://test"
    ) as client:
        result = (await client.post("/product", json={"url": URL})).json()
        assert result["price_eur"] is None and result["manual_reason"] == "browser_unavailable"
        async with worker.lock:
            result = (await client.post("/product", json={"url": URL})).json()
        assert result["manual_reason"] == "browser_busy"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"product_id": "08912573", "name": "Trousers", "price_eur": "35.95", "manual_reason": None},
        {"product_id": "wrong", "price_eur": "35.95"},
        {"product_id": "08912573", "price_eur": "NaN"},
        {"product_id": "08912573", "price_eur": None, "manual_reason": "http_403"},
        {},
    ],
)
async def test_browser_client_validates_result_and_never_returns_bad_price(monkeypatch, payload):
    import httpx

    factory = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: factory(transport=transport, **kwargs)
    )
    result = await importer.import_from_browser(
        importer.identify_product(URL), "http://browser:8080"
    )
    if payload.get("product_id") == "08912573" and payload.get("price_eur") == "35.95":
        assert str(result.price_eur) == "35.95" and result.source == "zara_browser"
    else:
        assert result.price_eur is None and result.manual_reason


@pytest.mark.asyncio
async def test_browser_timeout_returns_manual_input(monkeypatch):
    factory = httpx.AsyncClient

    def fail(request):
        raise httpx.ReadTimeout("timeout", request=request)

    transport = httpx.MockTransport(fail)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: factory(transport=transport, **kwargs)
    )
    result = await importer.import_from_browser(
        importer.identify_product(URL), "http://browser:8080"
    )
    assert result.price_eur is None and result.manual_reason == "browser_unavailable"
