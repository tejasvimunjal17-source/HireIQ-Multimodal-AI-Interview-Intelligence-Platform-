"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import health, interviews, root, sessions
from app.core.config import get_settings
from app.core.database import dispose_engine
from app.core.logging import configure_logging
from app.core.upload_limit import UploadSizeLimitMiddleware
from app.services.audio_intake import purge_stale_audio

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting %s v%s environment=%s", settings.app_name, __version__, settings.environment)
    try:
        purge_stale_audio(settings.audio_temp_dir, settings.audio_stale_after_hours * 3600)
    except OSError as exc:  # never block startup because of temp-file housekeeping
        logger.warning("Stale audio purge failed: %s", type(exc).__name__)
    yield
    dispose_engine()
    logger.info("Shutdown complete")


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never echo internals or request bodies (they may contain candidate data).
    logger.error(
        "Unhandled error method=%s path=%s error=%s", request.method, request.url.path, type(exc).__name__
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Multimodal AI interview intelligence platform - backend API.",
        lifespan=lifespan,
    )

    # Added BEFORE CORS so that CORS wraps it (413 responses still carry CORS headers).
    app.add_middleware(UploadSizeLimitMiddleware)

    origins = settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # Browsers reject credentials combined with the "*" wildcard.
        allow_credentials="*" not in origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(root.router)
    app.include_router(health.router)
    app.include_router(interviews.router)
    app.include_router(sessions.router)
    return app


app = create_app()
