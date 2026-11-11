import re
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter, field_validator


class RecipientInput(BaseModel):
    recipient_name: str = Field(min_length=3, max_length=200)
    phone: str = Field(min_length=7, max_length=50)
    telegram_username: str | None = Field(default=None, min_length=5, max_length=33)
    postal_code: str
    region: str = Field(default="", max_length=200)
    city: str = Field(min_length=2, max_length=200)
    address_line1: str = Field(min_length=5, max_length=300)
    address_line2: str = Field(default="", max_length=300)

    @field_validator("recipient_name")
    @classmethod
    def passport_name(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z '\-]+", value):
            raise ValueError("Имя получателя укажите латиницей как в паспорте")
        return value

    @field_validator("telegram_username", mode="before")
    @classmethod
    def username(cls, value):
        if value is None or isinstance(value, str) and not value.strip():
            return None
        if not isinstance(value, str):
            raise ValueError("Укажите Telegram username или пропустите поле")
        value = value.strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", value):
            raise ValueError("Укажите Telegram username получателя")
        return value

    @field_validator("postal_code")
    @classmethod
    def postcode(cls, value):
        if not re.fullmatch(r"\d{6}", value.strip()):
            raise ValueError("Индекс России должен содержать 6 цифр")
        return value.strip()

    @field_validator("phone")
    @classmethod
    def contact_phone(cls, value):
        value = re.sub(r"[ ()\-]", "", value.strip())
        if not re.fullmatch(r"\+?\d{7,15}", value):
            raise ValueError("Проверьте телефон получателя")
        return value


def validate_recipient_step(field: str, value: str | None):
    """Use the same normalizers and constraints as the complete API form."""
    info = RecipientInput.model_fields[field]
    normalizers = {
        "recipient_name": RecipientInput.passport_name,
        "phone": RecipientInput.contact_phone,
        "telegram_username": RecipientInput.username,
        "postal_code": RecipientInput.postcode,
    }
    if isinstance(value, str):
        value = value.strip()
    if field in normalizers:
        value = normalizers[field](value)
    annotation = Annotated[info.annotation, *info.metadata] if info.metadata else info.annotation
    return TypeAdapter(annotation).validate_python(value)


class NewOrderInput(BaseModel):
    customer_id: UUID
    address_id: UUID


class ItemInput(BaseModel):
    url: str = Field(max_length=3000)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    size: str = Field(min_length=1, max_length=64)
    color: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=1, le=100)
    name: str | None = Field(default=None, max_length=500)


class QuoteInput(BaseModel):
    close_order: bool = False


class CancelInput(BaseModel):
    item_ids: list[UUID] | None = None
    reason: str = Field(min_length=3, max_length=1000)


class ShippingCostInput(BaseModel):
    cost: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(pattern="^(RUB|EUR)$")
