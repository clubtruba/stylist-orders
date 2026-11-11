from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import CollectionStatus, ItemStatus, ShipmentStatus


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_id: UUID
    product_url: str
    size: str | None
    color: str | None
    quantity: int
    customer_note: str | None
    status: ItemStatus
    listed_price: Decimal | None
    listed_currency: str | None
    created_at: datetime


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    display_name: str
    phone: str | None
    collection_status: CollectionStatus


class AdminCustomerResponse(CustomerResponse):
    recipient_name: str | None = None
    country_code: str | None = None
    postal_code: str | None = None
    region: str | None = None
    city: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None


class DashboardResponse(BaseModel):
    to_buy: int
    on_the_way: int
    received: int
    assigned_to_shipment: int
    ordered: int
    purchased: int
    in_spain: int
    shipped: int
    active_shipments: int


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_id: UUID
    status: ShipmentStatus
    carrier: str | None
    tracking_number: str | None
    created_at: datetime
    item_ids: list[UUID] = Field(default_factory=list)


class CreateShipmentRequest(BaseModel):
    item_ids: list[UUID] = Field(min_length=1)
    carrier: str = Field(min_length=2, max_length=100)
    tracking_number: str = Field(min_length=3, max_length=200)


class ItemTrackingRequest(BaseModel):
    carrier: str = Field(min_length=2, max_length=100)
    tracking_number: str = Field(min_length=3, max_length=200)


class ItemStatusUpdateRequest(BaseModel):
    status: ItemStatus
    reason: str | None = None


class ItemStatusCorrectionRequest(BaseModel):
    status: ItemStatus
    reason: str = Field(min_length=3, max_length=500)


class CustomerProfileResponse(BaseModel):
    display_name: str
    phone: str | None
    country_code: str | None
    postal_code: str | None
    region: str | None
    city: str | None
    address_line1: str | None
    address_line2: str | None
    complete: bool


class CustomerProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=5, max_length=200)
    phone: str = Field(min_length=5, max_length=50)
    country_code: str = Field(min_length=2, max_length=2)
    postal_code: str = Field(min_length=2, max_length=32)
    region: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=2, max_length=200)
    address_line1: str = Field(min_length=5, max_length=300)
    address_line2: str | None = Field(default=None, max_length=300)

    @field_validator("display_name", "phone", "postal_code", "city", "address_line1")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field cannot be blank")
        return value

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isalpha():
            raise ValueError("country code must contain letters")
        return value


class PaymentEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    item_id: UUID
    note: str | None
    original_filename: str | None
    mime_type: str | None
    has_image: bool = False
    created_at: datetime
