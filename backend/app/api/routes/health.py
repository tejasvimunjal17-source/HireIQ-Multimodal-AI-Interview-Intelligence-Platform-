from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import __version__
from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse, ServiceHealth
from app.services import health_service

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Liveness only. Use /health/db and /health/redis for dependencies."""
    return HealthResponse(
        status="ok", service=settings.app_name, version=__version__, environment=settings.environment
    )


def _respond(result: ServiceHealth):
    # HTTP 503 when the dependency is NOT reachable, so monitors see a real failure.
    if result.status != "ok":
        return JSONResponse(status_code=503, content=result.model_dump())
    return result


@router.get("/db", response_model=ServiceHealth, responses={503: {"model": ServiceHealth}})
def health_db():
    return _respond(health_service.check_database())


@router.get("/redis", response_model=ServiceHealth, responses={503: {"model": ServiceHealth}})
def health_redis():
    return _respond(health_service.check_redis())
