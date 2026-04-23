"""Provide project functionality for the network monitoring project."""

from contextlib import asynccontextmanager
import logging
import time
import uuid

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api.deps import require_api_access
from .api.routes.auth import router as auth_router
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
from .db.session import SessionLocal
from .services.auth_service import ensure_bootstrap_admin
from .core.security import validate_auth_configuration
from .services.observability_service import record_exception, record_http_request, request_logging_context


logger = logging.getLogger("network_monitoring.http")


def _route_template(request) -> str | None:
    route = request.scope.get("route")
    if route is None:
        return None
    return getattr(route, "path_format", None) or getattr(route, "path", None)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        with request_logging_context(request_id):
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = (time.perf_counter() - start) * 1000
                record_exception(source="http")
                record_http_request(
                    path=request.url.path,
                    method=request.method,
                    status_code=500,
                    duration_ms=duration_ms,
                    route_path=_route_template(request),
                )
                logger.exception(
                    "Unhandled request exception method=%s path=%s duration_ms=%.2f",
                    request.method,
                    request.url.path,
                    duration_ms,
                )
                response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
            duration_ms = (time.perf_counter() - start) * 1000
            response.headers["X-Request-ID"] = request_id
            record_http_request(
                path=request.url.path,
                method=request.method,
                status_code=response.status_code,
                duration_ms=duration_ms,
                route_path=_route_template(request),
            )
            log_fn = logger.warning if duration_ms >= settings.request_slow_log_threshold_ms else logger.info
            log_fn(
                "request_completed method=%s path=%s status=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        docs_paths = {"/docs", "/redoc", "/openapi.json"}
        if request.url.path in docs_paths:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' https://cdn.jsdelivr.net; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; "
                "font-src 'self' https://cdn.jsdelivr.net data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    validate_auth_configuration()
    if settings.app_env.lower() != "production":
        await init_db()
    async with SessionLocal() as db:
        await ensure_bootstrap_admin(db)
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url=None if settings.app_env.lower() == "production" else "/docs",
    redoc_url=None if settings.app_env.lower() == "production" else "/redoc",
    openapi_url=None if settings.app_env.lower() == "production" else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.normalized_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["authorization", "x-api-key", "content-type"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.normalized_trusted_hosts)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

secured = [Depends(require_api_access)]

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"], dependencies=secured)
app.include_router(devices_router, prefix="/devices", tags=["devices"], dependencies=secured)
app.include_router(metrics_router, prefix="/metrics", tags=["metrics"], dependencies=secured)
app.include_router(alerts_router, prefix="/alerts", tags=["alerts"], dependencies=secured)
app.include_router(incidents_router, prefix="/incidents", tags=["incidents"], dependencies=secured)
app.include_router(system_router, prefix="/system", tags=["system"], dependencies=secured)
app.include_router(thresholds_router, prefix="/thresholds", tags=["thresholds"], dependencies=secured)
app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(observability_router, prefix="/observability", tags=["observability"], dependencies=secured)


@app.get("/")
async def root() -> dict:
    return {"message": f"{settings.app_name} API is running"}
