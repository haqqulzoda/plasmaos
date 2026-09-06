"""HTTP boundary: bounded multipart bodies, safe failures, origins and headers."""
import logging
from uuid import uuid4

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.formparsers import MultiPartException

from app.core.config import settings
from app.core.uploads import MAX_UPLOAD_REQUEST_BYTES

logger = logging.getLogger(__name__)


def safe_error(status: int, code: str, detail: str, request_id: str):
    return JSONResponse(status_code=status, content={"detail": detail, "code": code, "request_id": request_id})


async def validation_error(request, exc: RequestValidationError):
    # Pydantic errors include original input and arbitrary exception contexts.
    return safe_error(422, "invalid_request", "Invalid request", request.state.request_id)


async def internal_error(request, exc):
    logger.error("request_failed request_id=%s error_type=%s", request.state.request_id, type(exc).__name__)
    return safe_error(500, "internal_error", "Request could not be completed", request.state.request_id)


class HardenedHTTPMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        headers = dict(scope["headers"])
        is_upload = scope["path"].startswith("/api/v1/proposals/") and scope["path"].endswith("/upload-tz")
        size = 0
        started = False

        async def limited_receive():
            nonlocal size
            message = await receive()
            if is_upload and message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > MAX_UPLOAD_REQUEST_BYTES:
                    scope["state"]["upload_too_large"] = True
                    # This exception makes Starlette close every partial spool.
                    raise MultiPartException("Upload request exceeds the size limit")
            return message

        async def hardened_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                if scope["state"].get("upload_too_large"):
                    message["status"] = 413
                extra = [
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"same-origin"),
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", ("frame-ancestors 'self' " + " ".join(settings.BACKEND_CORS_ORIGINS)).encode()),
                ]
                if scope.get("scheme") == "https":
                    extra.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = message.get("headers", []) + extra
            await send(message)

        if scope["method"] not in {"GET", "HEAD", "OPTIONS"} and b"plasma_api_token=" in headers.get(b"cookie", b"") and not headers.get(b"authorization", b"").startswith(b"Bearer "):
            origin = headers.get(b"origin", b"").decode("latin-1")
            if origin not in settings.BACKEND_CORS_ORIGINS:
                return await safe_error(403, "untrusted_origin", "Untrusted request origin", request_id)(scope, receive, hardened_send)
        if is_upload:
            try:
                if int(headers.get(b"content-length", b"0")) > MAX_UPLOAD_REQUEST_BYTES:
                    return await safe_error(413, "upload_too_large", "Upload request exceeds the size limit", request_id)(scope, receive, hardened_send)
            except ValueError:
                return await safe_error(400, "invalid_request", "Invalid request", request_id)(scope, receive, hardened_send)
        try:
            await self.app(scope, limited_receive, hardened_send)
        except MultiPartException:
            if not started:
                await safe_error(413, "upload_too_large", "Upload request exceeds the size limit", request_id)(scope, receive, hardened_send)
        except Exception as exc:
            # Consume exceptions here so server traceback logging cannot print input.
            logger.error("request_failed request_id=%s error_type=%s", request_id, type(exc).__name__)
            if not started:
                await safe_error(500, "internal_error", "Request could not be completed", request_id)(scope, receive, hardened_send)
