from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import RequestActor, get_request_actor
from app.main import app
from app.models import UserRole
from app.schemas.catalog import CustomerResponse


def test_customer_can_access_only_own_customer_id():
    own_id, other_id = uuid4(), uuid4()
    actor = RequestActor(uuid4(), 42, UserRole.CUSTOMER, own_id)
    actor.require_customer_access(own_id)
    with pytest.raises(HTTPException) as exc:
        actor.require_customer_access(other_id)
    assert exc.value.status_code == 403


def test_admin_can_access_any_customer_id():
    actor = RequestActor(uuid4(), 1, UserRole.ADMIN, None)
    actor.require_customer_access(uuid4())
    actor.require_admin()


def test_customer_cannot_use_admin_routes():
    actor = RequestActor(uuid4(), 42, UserRole.CUSTOMER, uuid4())
    with pytest.raises(HTTPException) as exc:
        actor.require_admin()
    assert exc.value.status_code == 403


def test_viewer_can_read_staff_data_but_cannot_mutate():
    actor = RequestActor(uuid4(), 43, UserRole.VIEWER, uuid4())
    actor.require_staff()
    actor.require_customer_access(uuid4())
    with pytest.raises(HTTPException) as admin_exc:
        actor.require_admin()
    with pytest.raises(HTTPException) as customer_exc:
        actor.require_customer()
    assert admin_exc.value.status_code == 403
    assert customer_exc.value.status_code == 403


def test_customer_response_has_no_internal_note_or_financial_visibility():
    assert "internal_note" not in CustomerResponse.model_fields
    assert "financial_details_visible" not in CustomerResponse.model_fields


def test_missing_telegram_auth_is_unauthorized():
    response = TestClient(app).get("/api/v1/auth/me")
    assert response.status_code == 401


def test_customer_receives_403_from_admin_endpoint():
    actor = RequestActor(uuid4(), 42, UserRole.CUSTOMER, uuid4())
    app.dependency_overrides[get_request_actor] = lambda: actor
    try:
        response = TestClient(app).get("/api/v1/admin/customers")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
