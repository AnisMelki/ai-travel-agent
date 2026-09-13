from datetime import date
from langfuse import get_client
from agents import Agent
from pydantic import BaseModel

from app.agent.agent_runner import run_agent_with_retry
from app.exception.flight_exceptions import (
    FlightExtractionOutputError,
    UserCorrectableFlightError,
)
from app.hooks.flighs_run_hook import UsageRunHooks
from app.schema.chat_schema import ChatRequest
from app.schema.state_conversation import FlightConversationState, FlightRequestPatch
import logging


class FlightExtractionContext(BaseModel):
    origin: str | None = None
    destination: str | None = None
    departure_date: date | None = None
    return_date: date | None = None
    origin_code: str | None = None
    destination_code: str | None = None


logger = logging.getLogger(__name__)


class FlightExtractionContextFactory:
    def build(
        self,
        state: FlightConversationState,
    ) -> FlightExtractionContext:
        return FlightExtractionContext(
            origin=state.origin,
            destination=state.destination,
            departure_date=state.departure_date,
            return_date=state.return_date,
            origin_code=state.origin_code,
            destination_code=state.destination_code,
        )


class FlightRequestExtractionService:
    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.context_factory = FlightExtractionContextFactory()

    async def extract_flight_request(
        self, chat_request: ChatRequest, state: FlightConversationState
    ) -> FlightRequestPatch:
        logger.info(
            "Extracting flight request from user input: %s", chat_request.message
        )

        logger.info(
            "Extracting flight request",
            extra={
                "event": "flight_request_extraction",
                "conversation_id": state.conversation_id,
            },
        )

        langfuse = get_client()

        with langfuse.start_as_current_observation(
            as_type="chain",
            name="flight_request_extraction",
            input={
                "message": chat_request.message,
                "conversation_id": state.conversation_id,
            },
        ) as span:
            logger.info(
                "Starting flight request extraction span: trace_id=%s, span_id=%s",
                span.trace_id,
                span.id,
            )
            try:
                context = self.context_factory.build(state)

                run = await run_agent_with_retry(
                    self.agent,
                    chat_request.message,
                    context=context,
                    hooks=UsageRunHooks(),
                    conversation_id=state.conversation_id,
                )
                patch = run.result.final_output

                if patch is None or not patch.model_dump(exclude_none=True):
                    raise FlightExtractionOutputError(
                        message="No flight request could be extracted.",
                        details={"message": "No flight request could be extracted."},
                    )

                logger.info(
                    "Flight request extraction successful",
                    extra={
                        "event": "flight_request_extraction_success",
                        "conversation_id": state.conversation_id,
                        "patch": patch.model_dump(exclude_none=True).keys(),
                    },
                )
                span.update(
                    output={
                        "patch": patch.model_dump(mode="json", exclude_none=True),
                        "metrics": run.metrics.model_dump(mode="json"),
                    }
                )
                return patch

            except UserCorrectableFlightError as exc:
                span.update(level="WARNING", status_message=str(exc))
                logger.warning(
                    "Flight request extraction failed",
                    extra={
                        "event": "flight_request_extraction_failed",
                        "conversation_id": state.conversation_id,
                        "error": str(exc),
                    },
                )

                raise
            except Exception as exc:
                span.update(level="ERROR", status_message=str(exc))
                logger.exception(
                    "Flight request extraction failed",
                    extra={
                        "event": "flight_request_extraction_failed",
                        "conversation_id": state.conversation_id,
                        "error": str(exc),
                    },
                )
                raise
