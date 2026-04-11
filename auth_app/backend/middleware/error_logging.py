"""Global exception handler and structured request logging middleware."""

import time
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("NyayaDepaaAI")


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request: path, status, duration, user_id."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                f"UNHANDLED | {request.method} {request.url.path} | "
                f"{duration_ms:.1f}ms | {exc}",
                exc_info=True,
            )
            response = JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Internal server error"},
            )
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            user_id = getattr(getattr(request, "state", None), "user_id", "-")
            status = response.status_code if response else 500
            logger.info(
                f"{request.method} {request.url.path} | "
                f"status={status} | {duration_ms:.1f}ms | user={user_id} | "
                f"ip={request.client.host if request.client else '-'}"
            )
        return response


def register_exception_handlers(app: FastAPI) -> None:
    """Attach global exception handlers that return structured JSON errors."""

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal server error"},
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Resource not found"},
        )

    @app.exception_handler(422)
    async def validation_handler(request: Request, exc):
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Validation error", "details": str(exc)},
        )
