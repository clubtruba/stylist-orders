from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import RequestActor, get_request_actor
from app.db.session import engine, get_session
from app.main import app
from app.models import AppUser, UserRole


@pytest_asyncio.fixture
async def client():
    async with engine.connect() as connection:
        outer = await connection.begin()
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            user = AppUser(
                telegram_user_id=uuid4().int % 10**14,
                first_name="API stylist",
                role=UserRole.CUSTOMER,
            )
            session.add(user)
            await session.flush()
            actor = RequestActor(user.id, user.telegram_user_id, user.role, None)

            async def db():
                yield session

            app.dependency_overrides[get_session] = db
            app.dependency_overrides[get_request_actor] = lambda: actor
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as http:
                    yield http, actor
            finally:
                app.dependency_overrides.clear()
        await outer.rollback()


@pytest.mark.asyncio
async def test_recipient_order_item_roundtrip_and_admin_denial(client):
    http, actor = client
    recipient = await http.post(
        "/api/v1/recipients",
        json={
            "recipient_name": "IVAN IVANOV",
            "phone": "+79990000000",
            "telegram_username": "@example_user",
            "postal_code": "101000",
            "region": "Moscow",
            "city": "Moscow",
            "address_line1": "Test street 1",
        },
    )
    assert recipient.status_code == 200, recipient.text
    created = await http.post("/api/v1/orders", json=recipient.json())
    assert created.status_code == 200, created.text
    order = created.json()
    assert order["state"] == "DRAFT"
    response = await http.post(
        f"/api/v1/orders/{order['id']}/items",
        json={
            "url": "https://www2.hm.com/es_es/productpage.1352121001.html",
            "price": "19.99",
            "quantity": 2,
            "size": "M",
            "color": "black",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total_eur"] == "47.98"
    listed = await http.get("/api/v1/orders")
    assert listed.status_code == 200 and len(listed.json()) == 1
    denied = await http.post(
        f"/api/v1/orders/{order['id']}/cancel", json={"reason": "Test cancellation"}
    )
    assert denied.status_code == 403
    app.dependency_overrides[get_request_actor] = lambda: RequestActor(
        uuid4(), 999, UserRole.CUSTOMER, None
    )
    assert (await http.get(f"/api/v1/orders/{order['id']}")).status_code == 409
    assert (await http.get("/api/v1/orders")).json() == []


@pytest.mark.asyncio
async def test_russian_postcode_and_passport_name_validation(client):
    http, _ = client
    response = await http.post(
        "/api/v1/recipients",
        json={
            "recipient_name": "Иван Иванов",
            "phone": "+79990000000",
            "telegram_username": "example_user",
            "postal_code": "123",
            "city": "Moscow",
            "address_line1": "Test street 1",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unauthenticated_orders_are_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/orders")).status_code == 401
