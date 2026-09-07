"""Unified error model. Every error the API returns has the same envelope:
``{"error": {"code", "message", "request_id", "details"}}`` — clients (and
interviewers reading the code) only ever need one error contract.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_var

log = get_logger("errors")


class AppError(Exception):
    """Business-level error with a stable machine code."""

    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(
        self, code: str, message: str, *, details: Any = None, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        if status_code is not None:
            self.status_code = status_code


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, resource: str, ident: Any = None) -> None:
        super().__init__(
            f"{resource}.not_found", f"{resource} not found", details={"id": str(ident)}
        )


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT


class PermissionDenied(AppError):
    status_code = status.HTTP_403_FORBIDDEN

    def __init__(self, required: str | None = None) -> None:
        super().__init__(
            "permission.denied",
            "you do not have permission to perform this action",
            details={"required": required} if required else None,
        )


class Unauthenticated(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(
        self, code: str = "auth.required", message: str = "authentication required"
    ) -> None:
        super().__init__(code, message)


class ValidationFailed(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__("validation.failed", message, details=details, status_code=422)


class RateLimited(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS

    def __init__(self, scope: str) -> None:
        super().__init__("rate.limited", "too many requests", details={"scope": scope})


def _envelope(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id_var.get(),
            "details": details,
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope("validation.failed", "request validation failed", exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {401: "auth.required", 403: "permission.denied", 404: "not_found"}
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(codes.get(exc.status_code, "http.error"), str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # never leak internals; log with full stack for observability
        log.error("unhandled_exception", exc=repr(exc), request_id=request_id_var.get())
        return JSONResponse(
            status_code=500,
            content=_envelope("internal.error", "internal server error"),
        )
