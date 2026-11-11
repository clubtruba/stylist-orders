from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.domain.item_workflow import ensure_item_transition
from app.models import AuditLog, Customer, Item, ItemStatus, ItemStatusHistory, NotificationOutbox


@dataclass(frozen=True)
class CreateItemCommand:
    customer_id: UUID
    product_url: str
    size: str | None = None
    color: str | None = None
    quantity: int = 1
    customer_note: str | None = None


class ItemService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, command: CreateItemCommand) -> Item:
        if command.quantity < 1:
            raise ValueError("quantity must be at least 1")
        item = Item(
            customer_id=command.customer_id,
            product_url=command.product_url,
            size=command.size,
            color=command.color,
            quantity=command.quantity,
            customer_note=command.customer_note,
            status=ItemStatus.TO_BUY,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def transition(
        self, item_id: UUID, target: ItemStatus, actor_user_id: UUID, reason: str | None = None
    ) -> Item:
        result = await self.session.execute(
            select(Item).where(Item.id == item_id).with_for_update()
        )
        item = result.scalar_one()
        ensure_item_transition(item.status, target)
        previous = item.status
        item.status = target
        self.session.add(
            ItemStatusHistory(
                item_id=item.id,
                from_status=previous,
                to_status=target,
                changed_by_user_id=actor_user_id,
                reason=reason,
            )
        )
        recipient_user_id = await self.session.scalar(
            select(Customer.app_user_id).where(Customer.id == item.customer_id)
        )
        if recipient_user_id is not None:
            self.session.add(
                NotificationOutbox(
                    recipient_user_id=recipient_user_id,
                    event_type="ITEM_STATUS_CHANGED",
                    payload={"item_id": str(item.id), "from": previous.value, "to": target.value},
                )
            )
        await self.session.flush()
        return item

    async def correct_status(
        self, item_id: UUID, target: ItemStatus, actor_user_id: UUID, reason: str
    ) -> Item:
        result = await self.session.execute(
            select(Item).where(Item.id == item_id).with_for_update()
        )
        item = result.scalar_one()
        previous = item.status
        if previous is target:
            raise ValueError("new status must differ from current status")
        item.status = target
        self.session.add_all([
            ItemStatusHistory(
                item_id=item.id,
                from_status=previous,
                to_status=target,
                changed_by_user_id=actor_user_id,
                reason=f"ADMIN CORRECTION: {reason}",
            ),
            AuditLog(
                actor_user_id=actor_user_id,
                action="ITEM_STATUS_CORRECTED",
                entity_type="ITEM",
                entity_id=item.id,
                payload={"from": previous.value, "to": target.value, "reason": reason},
            ),
        ])
        await self._queue_status_notification(item, previous, target)
        await self.session.flush()
        return item

    async def _queue_status_notification(
        self, item: Item, previous: ItemStatus, target: ItemStatus
    ) -> None:
        recipient_user_id = await self.session.scalar(
            select(Customer.app_user_id).where(Customer.id == item.customer_id)
        )
        if recipient_user_id is not None:
            self.session.add(NotificationOutbox(
                recipient_user_id=recipient_user_id,
                event_type="ITEM_STATUS_CHANGED",
                payload={"item_id": str(item.id), "from": previous.value, "to": target.value},
            ))
