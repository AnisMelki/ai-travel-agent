import logging
from datetime import UTC, date, datetime

from agents import Agent
from langfuse import get_client
from pydantic import BaseModel, Field

from app.agent.agent_runner import run_agent_with_retry
from app.exception.flight_exceptions import (
    FlightExtractionOutputError,
    UserCorrectableFlightError,
)
from app.hooks.flighs_run_hook import UsageRunHooks
from app.schema.chat_schema import ChatRequest
from app.schema.state_conversation import (
    ConversationMessage,
    FlightAgentResponse,
    FlightConversationState,
)


class FlightExtractionContext(BaseModel):
    origin: str | None = None
    destination: str | None = None
    departure_date: date | None = None
    return_date: date | None = None
    origin_code: str | None = None
    destination_code: str | None = None
    history: list[ConversationMessage] = Field(default_factory=list)
    current_date: date | None = None


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
            history=state.history,
            current_date=datetime.now(UTC).date(),
        )


class FlightRequestExtractionService:
    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.context_factory = FlightExtractionContextFactory()

    async def extract_flight_request(
        self, chat_request: ChatRequest, state: FlightConversationState
    ) -> FlightAgentResponse:
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
                agent_response = run.result.final_output

                # `type` is always set, so emptiness must be judged on the payload.
                if agent_response is None or not (
                    agent_response.patch.model_dump(exclude_none=True)
                    or agent_response.reply
                ):
                    raise FlightExtractionOutputError(
                        message="No flight request could be extracted.",
                        details={"message": "No flight request could be extracted."},
                    )

                logger.info(
                    "Flight request extraction successful",
                    extra={
                        "event": "flight_request_extraction_success",
                        "conversation_id": state.conversation_id,
                        "response_type": agent_response.type,
                        "patch": sorted(
                            agent_response.patch.model_dump(exclude_none=True)
                        ),
                        "has_reply": agent_response.reply is not None,
                    },
                )
                span.update(
                    output={
                        "response": agent_response.model_dump(
                            mode="json", exclude_none=True
                        ),
                        "metrics": run.metrics.model_dump(mode="json"),
                    }
                )
                return agent_response

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
