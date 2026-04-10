from contextlib import asynccontextmanager
import logging
import time
import uuid

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

from .api.routes.dashboard import router as dashboard_router
from .api.routes.devices import router as devices_router
from .api.routes.metrics import router as metrics_router
from .api.routes.alerts import router as alerts_router
from .api.routes.incidents import router as incidents_router
from .api.routes.system import router as system_router
from .api.routes.thresholds import router as thresholds_router
from .api.routes.health import router as health_router
from .api.routes.observability import router as observability_router
from .core.config import configure_logging, settings
from .db.init_db import init_db
from .scheduler.scheduler import create_scheduler


logger = logging.getLogger("network_monitoring.http")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    if settings.app_env.lower() != "production":
        init_db()
    scheduler = None
    if settings.scheduler_enabled:
        scheduler = create_scheduler()
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
app.include_router(devices_router, prefix="/devices", tags=["devices"])
app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
app.include_router(alerts_router, prefix="/alerts", tags=["alerts"])
app.include_router(incidents_router, prefix="/incidents", tags=["incidents"])
app.include_router(system_router, prefix="/system", tags=["system"])
app.include_router(thresholds_router, prefix="/thresholds", tags=["thresholds"])
app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(observability_router, prefix="/observability", tags=["observability"])


@app.get("/")
async def root() -> dict:
    return {"message": f"{settings.app_name} API is running"}
