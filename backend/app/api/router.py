from fastapi import APIRouter, Depends

from app.auth.dependencies import RequestActor, get_request_actor

router = APIRouter(prefix="/api/v1")


@router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/auth/me", tags=["auth"])
async def auth_me(actor: RequestActor = Depends(get_request_actor)) -> dict[str, str | None]:
    return {
        "app_user_id": str(actor.app_user_id),
        "role": actor.role.value,
        "customer_id": str(actor.customer_id) if actor.customer_id else None,
    }
