import json
import logging
from agents import RunContextWrapper

from app.context.flight_context import FlightAgentContext
from app.exception.flight_exceptions import (
    AirportNotFoundError,
    AmbiguityAirportError,
    EmptyFlightSearch,
    FlightRequestValidationError,
)

logger = logging.getLogger(__name__)


def flight_tool_error_handler(
    context: RunContextWrapper[FlightAgentContext],
    error: Exception,
) -> str:
    """
    Convert expected flight-domain exceptions into structured tool results
    that the LLM can understand.

    Unexpected programming errors are re-raised.
    """

    logger.warning(
        "Flight tool failed",
        exc_info=error,
        extra={
            "event": "flight_tool_error",
            "error_type": type(error).__name__,
        },
    )

    if isinstance(error, AirportNotFoundError):
        return json.dumps(
            {
                "status": "error",
                "error_code": "AIRPORT_NOT_FOUND",
                "recoverable": True,
                "message": str(error),
                "details": {
                    "location": error.location,
                },
                "agent_action": (
                    "Ask the user to provide another city or a valid airport code."
                ),
            }
        )

    if isinstance(error, AmbiguityAirportError):
        return json.dumps(
            {
                "status": "error",
                "error_code": "AMBIGUOUS_AIRPORT",
                "recoverable": True,
                "message": str(error),
                "details": {
                    "location": error.location,
                    "airport_codes": error.airport_codes,
                },
                "agent_action": (
                    "Ask the user to choose one of the provided airports. "
                    "Do not call the flight search tool again until they choose."
                ),
            }
        )

    if isinstance(error, EmptyFlightSearch):
        return json.dumps(
            {
                "status": "error",
                "error_code": "NO_FLIGHTS_FOUND",
                "recoverable": True,
                "message": str(error),
                "details": {},
                "agent_action": (
                    "Tell the user that no flights were found and suggest "
                    "changing the date or airports."
                ),
            }
        )
    if isinstance(error, FlightRequestValidationError):
        return json.dumps(
            {
                "status": "error",
                "error_code": "FLIGHT_REQUEST_VALIDATION_ERROR",
                "recoverable": True,
                "message": str(error),
                "details": {
                    "errors": error.errors,
                },
                "agent_action": (
                    "Ask the user to correct the highlighted errors in the flight request."
                ),
            }
        )

    # Une erreur inconnue est probablement un bug de programmation.
    logger.exception(
        "Unexpected flight tool error",
        exc_info=error,
    )
    raise error
