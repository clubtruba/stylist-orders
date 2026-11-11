from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExchangeRate


def moscow_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def parse_cbr(xml: bytes, requested: date) -> tuple[date, Decimal]:
    if len(xml) > 1_000_000 or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("Invalid exchange-rate document")
    root = ElementTree.fromstring(xml)
    effective = datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date()
    if effective > requested or (requested - effective).days > 14:
        raise ValueError("Exchange-rate effective date is invalid")
    for entry in root.findall("Valute"):
        if entry.findtext("CharCode") == "EUR":
            try:
                rate = Decimal(entry.findtext("Value", "").replace(",", "."))
                nominal = Decimal(entry.findtext("Nominal", ""))
                if not rate.is_finite() or not nominal.is_finite() or rate <= 0 or nominal <= 0:
                    raise ValueError("Invalid EUR exchange rate")
                return effective, rate / nominal
            except InvalidOperation as exc:
                raise ValueError("Invalid EUR exchange rate") from exc
    raise ValueError("EUR exchange rate is missing")


async def current_rate(session: AsyncSession) -> ExchangeRate:
    today = moscow_today()
    saved = await session.scalar(select(ExchangeRate).where(ExchangeRate.business_date == today))
    if saved:
        return saved
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        response = await client.get(
            "https://www.cbr.ru/scripts/XML_daily.asp",
            params={"date_req": today.strftime("%d/%m/%Y")},
        )
        response.raise_for_status()
    effective, eur_rub = parse_cbr(response.content, today)
    await session.execute(
        insert(ExchangeRate)
        .values(business_date=today, effective_date=effective, eur_rub=eur_rub)
        .on_conflict_do_nothing(index_elements=["business_date"])
    )
    return (
        await session.scalars(select(ExchangeRate).where(ExchangeRate.business_date == today))
    ).one()
