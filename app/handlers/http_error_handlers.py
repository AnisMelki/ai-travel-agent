import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exception.flight_exceptions import (
    AirlineReviewProviderTimeoutError,
    EmptyFlightSearch,
    FlightError,
    FlightProviderTimeoutError,
    ProviderError,
    UserCorrectableFlightError,
)
from app.repositories.redis_conversation_repository import ConversationStorageError
from app.schema.chat_schema import ErrorResponse

logger = logging.getLogger(__name__)

# Provider internals (actor ids, dataset ids, upstream messages) stay in the logs.
_PROVIDER_MESSAGE = "The flight provider is temporarily unavailable."
_TIMEOUT_MESSAGE = "The flight provider took too long to respond."
_STORAGE_MESSAGE = "The conversation could not be reached. Please retry."
_UNEXPECTED_MESSAGE = "An unexpected error occurred."


def _error_response(
    status_code: int,
    message: str,
    error_code: str,
    *,
    retryable: bool,
) -> JSONResponse:
    body = ErrorResponse(
        type="error",
        message=message,
        error_code=error_code,
        retryable=retryable,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def _handle_empty_flight_search(request: Request, exc: Exception) -> JSONResponse:
    error = cast_flight_error(exc)
    logger.info("No flights found", extra={"details": error.details})
    return _error_response(404, error.message, error.code, retryable=False)


async def _handle_user_correctable(request: Request, exc: Exception) -> JSONResponse:
    error = cast_flight_error(exc)
    logger.info(
        "User correctable flight error",
        extra={"error_code": error.code, "details": error.details},
    )
    return _error_response(400, error.message, error.code, retryable=False)


async def _handle_provider_timeout(request: Request, exc: Exception) -> JSONResponse:
    error = cast_flight_error(exc)
    logger.error(
        "Flight provider timed out",
        extra={"error_code": error.code, "details": error.details},
    )
    return _error_response(504, _TIMEOUT_MESSAGE, error.code, retryable=True)


async def _handle_provider_error(request: Request, exc: Exception) -> JSONResponse:
    error = cast_flight_error(exc)
    logger.error(
        "Flight provider failed",
        extra={"error_code": error.code, "details": error.details},
    )
    return _error_response(502, _PROVIDER_MESSAGE, error.code, retryable=True)


async def _handle_flight_error(request: Request, exc: Exception) -> JSONResponse:
    error = cast_flight_error(exc)
    logger.exception("Unhandled flight domain error", extra={"error_code": error.code})
    return _error_response(500, _UNEXPECTED_MESSAGE, error.code, retryable=False)


async def _handle_storage_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Conversation storage unavailable")
    return _error_response(
        503, _STORAGE_MESSAGE, "conversation_storage_unavailable", retryable=True
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unexpected error processing request")
    return _error_response(500, _UNEXPECTED_MESSAGE, "internal_error", retryable=False)


def cast_flight_error(exc: Exception) -> FlightError:
    if not isinstance(exc, FlightError):  # pragma: no cover - guarded by registration
        raise exc
    return exc


def register_exception_handlers(app: FastAPI) -> None:
    """Starlette dispatches on the exception's MRO, so the most specific wins."""
    app.add_exception_handler(EmptyFlightSearch, _handle_empty_flight_search)
    app.add_exception_handler(UserCorrectableFlightError, _handle_user_correctable)
    app.add_exception_handler(FlightProviderTimeoutError, _handle_provider_timeout)
    app.add_exception_handler(
        AirlineReviewProviderTimeoutError, _handle_provider_timeout
    )
    app.add_exception_handler(ProviderError, _handle_provider_error)
    app.add_exception_handler(FlightError, _handle_flight_error)
    app.add_exception_handler(ConversationStorageError, _handle_storage_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
