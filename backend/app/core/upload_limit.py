"""Reject oversized audio uploads from the Content-Length header, BEFORE the body is parsed.

(The streaming check inside audio_intake.save_upload is the second line of defence;
a reverse proxy should also enforce a body limit in production.)
"""

import re

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

UPLOAD_PATH = re.compile(r"^/api/sessions/[^/]+/responses/?$")
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


class UploadSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and UPLOAD_PATH.match(request.url.path):
            raw = request.headers.get("content-length")
            if raw is not None:
                try:
                    length = int(raw)
                except ValueError:
                    return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
                limit = get_settings().audio_max_upload_bytes + MULTIPART_OVERHEAD_BYTES
                if length > limit:
                    return JSONResponse(status_code=413, content={"detail": "Upload is too large."})
        return await call_next(request)
