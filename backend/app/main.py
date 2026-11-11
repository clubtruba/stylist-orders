from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.api.catalog import router as catalog_router
from app.core.config import get_settings
from app.api.orders import router as orders_router
from app.services.orders import OrderError
from fastapi import Request
from fastapi.responses import JSONResponse

settings = get_settings()
app = FastAPI(title="Stylist Orders API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(catalog_router)
app.include_router(orders_router)


@app.exception_handler(OrderError)
async def order_error_handler(request: Request, exc: OrderError):
    return JSONResponse(status_code=409, content={'detail':str(exc)})
