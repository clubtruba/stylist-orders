from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import RequestActor, get_request_actor
from app.core.config import get_settings
from app.db.session import get_session
from app.models import (
    Customer,
    CustomerAddress,
    CustomerShipment,
    Item,
    ItemStatus,
    PaymentEvidence,
    ShipmentItem,
    UserRole,
)
from app.domain.item_workflow import InvalidItemTransition
from app.schemas.catalog import (
    AdminCustomerResponse,
    CustomerProfileResponse,
    CustomerProfileUpdateRequest,
    CustomerResponse,
    CreateShipmentRequest,
    DashboardResponse,
    ItemResponse,
    ItemTrackingRequest,
    ItemStatusCorrectionRequest,
    ItemStatusUpdateRequest,
    PaymentEvidenceResponse,
    ShipmentResponse,
)
from app.services.items import ItemService
from app.services.payment_evidence import PaymentEvidenceError, PaymentEvidenceService
from app.services.shipments import CreateShipmentCommand, ShipmentService, ShipmentValidationError

router = APIRouter(prefix="/api/v1", dependencies=[Depends(get_request_actor)])


def profile_response(customer: Customer, address: CustomerAddress | None) -> CustomerProfileResponse:
    return CustomerProfileResponse(
        display_name=customer.display_name,
        phone=customer.phone,
        country_code=address.country_code if address else None,
        postal_code=address.postal_code if address else None,
        region=address.region if address else None,
        city=address.city if address else None,
        address_line1=address.address_line1 if address else None,
        address_line2=address.address_line2 if address else None,
        complete=bool(customer.phone and address),
    )


def evidence_response(evidence: PaymentEvidence) -> PaymentEvidenceResponse:
    return PaymentEvidenceResponse(
        id=evidence.id,
        item_id=evidence.item_id,
        note=evidence.note,
        original_filename=evidence.original_filename,
        mime_type=evidence.mime_type,
        has_image=bool(evidence.stored_filename),
        created_at=evidence.created_at,
    )


async def shipment_response(session: AsyncSession, shipment: CustomerShipment) -> ShipmentResponse:
    item_ids = list((await session.scalars(select(ShipmentItem.item_id).where(
        ShipmentItem.shipment_id == shipment.id
    ))).all())
    return ShipmentResponse(
        id=shipment.id,
        customer_id=shipment.customer_id,
        status=shipment.status,
        carrier=shipment.carrier,
        tracking_number=shipment.tracking_number,
        created_at=shipment.created_at,
        item_ids=item_ids,
    )


@router.get("/items", response_model=list[ItemResponse], tags=["items"])
async def list_items(actor: RequestActor = Depends(get_request_actor),
                     session: AsyncSession = Depends(get_session)):
    query = select(Item).order_by(Item.created_at.desc())
    if actor.role is UserRole.CUSTOMER:
        if actor.customer_id is None:
            return []
        query = query.where(Item.customer_id == actor.customer_id)
    return list((await session.scalars(query)).all())


@router.get("/items/{item_id}", response_model=ItemResponse, tags=["items"])
async def get_item(item_id: UUID, actor: RequestActor = Depends(get_request_actor),
                   session: AsyncSession = Depends(get_session)):
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    actor.require_customer_access(item.customer_id)
    return item


@router.get("/customers/{customer_id}", response_model=CustomerResponse, tags=["customers"])
async def get_customer(customer_id: UUID, actor: RequestActor = Depends(get_request_actor),
                       session: AsyncSession = Depends(get_session)):
    actor.require_customer_access(customer_id)
    customer = await session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.get("/profile", response_model=CustomerProfileResponse, tags=["customers"])
async def get_profile(actor: RequestActor = Depends(get_request_actor),
                      session: AsyncSession = Depends(get_session)):
    if actor.customer_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    customer = await session.get(Customer, actor.customer_id)
    address = await session.scalar(select(CustomerAddress).where(
        CustomerAddress.customer_id == actor.customer_id,
        CustomerAddress.is_default.is_(True),
    ))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return profile_response(customer, address)


@router.put("/profile", response_model=CustomerProfileResponse, tags=["customers"])
async def update_profile(
    command: CustomerProfileUpdateRequest,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_customer()
    if actor.customer_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    customer = await session.get(Customer, actor.customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    address = await session.scalar(select(CustomerAddress).where(
        CustomerAddress.customer_id == actor.customer_id,
        CustomerAddress.is_default.is_(True),
    ).with_for_update())
    customer.display_name = command.display_name.strip()
    customer.phone = command.phone.strip()
    values = command.model_dump(exclude={"display_name"})
    values["phone"] = customer.phone
    if address is None:
        address = CustomerAddress(
            customer_id=actor.customer_id,
            label="Основной адрес",
            recipient_name=customer.display_name,
            is_default=True,
            **values,
        )
        session.add(address)
    else:
        address.recipient_name = customer.display_name
        for field, value in values.items():
            setattr(address, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    return profile_response(customer, address)


@router.get("/admin/customers", response_model=list[AdminCustomerResponse], tags=["admin"])
async def admin_customers(actor: RequestActor = Depends(get_request_actor),
                          session: AsyncSession = Depends(get_session)):
    actor.require_staff()
    rows = (await session.execute(
        select(Customer, CustomerAddress)
        .outerjoin(CustomerAddress, (
            (CustomerAddress.customer_id == Customer.id) & CustomerAddress.is_default.is_(True)
        ))
        .order_by(Customer.display_name)
    )).all()
    return [AdminCustomerResponse(
        id=customer.id,
        display_name=customer.display_name,
        phone=customer.phone,
        collection_status=customer.collection_status,
        recipient_name=address.recipient_name if address else None,
        country_code=address.country_code if address else None,
        postal_code=address.postal_code if address else None,
        region=address.region if address else None,
        city=address.city if address else None,
        address_line1=address.address_line1 if address else None,
        address_line2=address.address_line2 if address else None,
    ) for customer, address in rows]


@router.get("/dashboard", response_model=DashboardResponse, tags=["dashboard"])
async def dashboard(actor: RequestActor = Depends(get_request_actor),
                    session: AsyncSession = Depends(get_session)):
    query = select(Item.status, func.count(Item.id)).group_by(Item.status)
    active_shipments_query = select(func.count(func.distinct(ShipmentItem.shipment_id))).join(
        Item, Item.id == ShipmentItem.item_id
    ).where(Item.status == ItemStatus.SHIPPED)
    if actor.role is UserRole.CUSTOMER:
        if actor.customer_id is None:
            counts = {}
            active_shipments = 0
        else:
            counts = dict((await session.execute(query.where(
                Item.customer_id == actor.customer_id))).all())
            active_shipments = await session.scalar(active_shipments_query.where(
                Item.customer_id == actor.customer_id
            )) or 0
    else:
        counts = dict((await session.execute(query)).all())
        active_shipments = await session.scalar(active_shipments_query) or 0
    return DashboardResponse(
        to_buy=counts.get(ItemStatus.TO_BUY, 0),
        on_the_way=counts.get(ItemStatus.ON_THE_WAY_TO_US, 0),
        received=counts.get(ItemStatus.RECEIVED, 0),
        assigned_to_shipment=counts.get(ItemStatus.ASSIGNED_TO_SHIPMENT, 0),
        ordered=counts.get(ItemStatus.TO_BUY, 0),
        purchased=sum(counts.get(value, 0) for value in (
            ItemStatus.ORDERED, ItemStatus.ON_THE_WAY_TO_US, ItemStatus.READY_FOR_PICKUP
        )),
        in_spain=sum(counts.get(value, 0) for value in (
            ItemStatus.PURCHASED_OFFLINE, ItemStatus.RECEIVED, ItemStatus.ASSIGNED_TO_SHIPMENT
        )),
        shipped=counts.get(ItemStatus.SHIPPED, 0) + counts.get(ItemStatus.DELIVERED, 0),
        active_shipments=active_shipments,
    )


@router.get("/shipments", response_model=list[ShipmentResponse], tags=["shipments"])
async def list_shipments(
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    query = select(CustomerShipment).order_by(CustomerShipment.created_at.desc())
    if actor.role is UserRole.CUSTOMER:
        if actor.customer_id is None:
            return []
        query = query.where(CustomerShipment.customer_id == actor.customer_id)
    shipments = list((await session.scalars(query)).all())
    return [await shipment_response(session, shipment) for shipment in shipments]


@router.post(
    "/admin/customers/{customer_id}/shipments",
    response_model=ShipmentResponse,
    tags=["admin"],
)
async def create_and_dispatch_shipment(
    customer_id: UUID,
    command: CreateShipmentRequest,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_admin()
    address_id = await session.scalar(select(CustomerAddress.id).where(
        CustomerAddress.customer_id == customer_id,
        CustomerAddress.is_default.is_(True),
    ))
    if address_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer has no address")
    service = ShipmentService(session)
    try:
        shipment = await service.create(CreateShipmentCommand(
            customer_id=customer_id,
            address_id=address_id,
            item_ids=tuple(command.item_ids),
            actor_user_id=actor.app_user_id,
        ))
        await service.dispatch(
            shipment.id, command.carrier, command.tracking_number, actor.app_user_id
        )
        await session.commit()
        return await shipment_response(session, shipment)
    except ShipmentValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put(
    "/admin/items/{item_id}/tracking",
    response_model=ShipmentResponse,
    tags=["admin"],
)
async def save_item_tracking(
    item_id: UUID,
    command: ItemTrackingRequest,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_admin()
    try:
        shipment = await ShipmentService(session).save_tracking_for_shipped_item(
            item_id, command.carrier, command.tracking_number, actor.app_user_id
        )
        await session.commit()
        return await shipment_response(session, shipment)
    except ShipmentValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/admin/warehouse", response_model=list[ItemResponse], tags=["admin"])
async def warehouse(actor: RequestActor = Depends(get_request_actor),
                    session: AsyncSession = Depends(get_session)):
    actor.require_staff()
    query = select(Item).where(Item.status.in_([
        ItemStatus.PURCHASED_OFFLINE,
        ItemStatus.RECEIVED,
        ItemStatus.ASSIGNED_TO_SHIPMENT,
    ])).order_by(Item.customer_id)
    return list((await session.scalars(query)).all())


@router.patch("/admin/items/{item_id}/status", response_model=ItemResponse, tags=["admin"])
async def update_item_status(
    item_id: UUID,
    command: ItemStatusUpdateRequest,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_admin()
    if command.status in {ItemStatus.ASSIGNED_TO_SHIPMENT, ItemStatus.SHIPPED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Create a customer shipment to assign or ship items",
        )
    try:
        item = await ItemService(session).transition(
            item_id, command.status, actor.app_user_id, command.reason
        )
        await session.commit()
        return item
    except NoResultFound as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found") from exc
    except InvalidItemTransition as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/admin/items/{item_id}/status-correction", response_model=ItemResponse, tags=["admin"])
async def correct_item_status(
    item_id: UUID,
    command: ItemStatusCorrectionRequest,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_admin()
    try:
        item = await ItemService(session).correct_status(
            item_id, command.status, actor.app_user_id, command.reason.strip()
        )
        await session.commit()
        return item
    except NoResultFound as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found") from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/admin/payment-evidence",
    response_model=list[PaymentEvidenceResponse],
    tags=["admin"],
)
async def list_payment_evidence(
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_staff()
    evidence = (await session.scalars(
        select(PaymentEvidence).order_by(PaymentEvidence.created_at.desc())
    )).all()
    return [evidence_response(value) for value in evidence]


@router.post(
    "/admin/items/{item_id}/payment-evidence",
    response_model=PaymentEvidenceResponse,
    tags=["admin"],
)
async def add_payment_evidence(
    item_id: UUID,
    note: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_admin()
    content = await image.read() if image else None
    try:
        evidence = await PaymentEvidenceService(
            session, get_settings().payment_proof_dir
        ).create(
            item_id,
            actor.app_user_id,
            admin=True,
            note=note,
            content=content,
            mime_type=image.content_type if image else None,
            original_filename=image.filename if image else None,
        )
        await session.commit()
        return evidence_response(evidence)
    except PaymentEvidenceError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/admin/payment-evidence/{evidence_id}/image", tags=["admin"])
async def payment_evidence_image(
    evidence_id: UUID,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_staff()
    evidence = await session.get(PaymentEvidence, evidence_id)
    if evidence is None or not evidence.stored_filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    path = Path(get_settings().payment_proof_dir) / evidence.stored_filename
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    return FileResponse(path, media_type=evidence.mime_type or "application/octet-stream")
