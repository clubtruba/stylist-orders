from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Item, PaymentEvidence


ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class PaymentEvidenceError(ValueError):
    pass


class PaymentEvidenceService:
    def __init__(self, session: AsyncSession, storage_dir: str):
        self.session = session
        self.storage_dir = Path(storage_dir)

    async def ensure_item_access(self, item_id: UUID, user_id: UUID, admin: bool) -> Item:
        item = await self.session.get(Item, item_id)
        if item is None:
            raise PaymentEvidenceError("Order not found")
        if not admin:
            owner_id = await self.session.scalar(
                select(Customer.app_user_id).where(Customer.id == item.customer_id)
            )
            if owner_id != user_id:
                raise PaymentEvidenceError("Order not found")
        return item

    def save_image(self, content: bytes, mime_type: str, original_filename: str | None) -> str:
        if mime_type not in ALLOWED_IMAGE_TYPES:
            raise PaymentEvidenceError("Only JPEG, PNG or WebP images are allowed")
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise PaymentEvidenceError("Image must be between 1 byte and 10 MB")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        stored_filename = f"{uuid4().hex}{ALLOWED_IMAGE_TYPES[mime_type]}"
        (self.storage_dir / stored_filename).write_bytes(content)
        return stored_filename

    async def create(
        self,
        item_id: UUID,
        user_id: UUID,
        *,
        admin: bool,
        note: str | None = None,
        content: bytes | None = None,
        mime_type: str | None = None,
        original_filename: str | None = None,
        telegram_file_id: str | None = None,
        telegram_file_unique_id: str | None = None,
    ) -> PaymentEvidence:
        await self.ensure_item_access(item_id, user_id, admin)
        cleaned_note = note.strip()[:4000] if note and note.strip() else None
        stored_filename = None
        if content is not None:
            stored_filename = self.save_image(content, mime_type or "", original_filename)
        if cleaned_note is None and stored_filename is None:
            raise PaymentEvidenceError("Add a note or an image")
        evidence = PaymentEvidence(
            item_id=item_id,
            submitted_by_user_id=user_id,
            note=cleaned_note,
            original_filename=(original_filename or "")[:255] or None,
            stored_filename=stored_filename,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            mime_type=mime_type,
        )
        self.session.add(evidence)
        await self.session.flush()
        return evidence
