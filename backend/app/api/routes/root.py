from fastapi import APIRouter, Depends

from app import __version__
from app.core.config import Settings, get_settings
from app.schemas.health import RootResponse

router = APIRouter(tags=["root"])


@router.get("/", response_model=RootResponse)
def read_root(settings: Settings = Depends(get_settings)) -> RootResponse:
    return RootResponse(
        name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        docs_url="/docs",
        health_url="/health",
    )
