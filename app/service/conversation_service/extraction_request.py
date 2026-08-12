import logging
from agents import Agent, Runner
from pydantic import BaseModel
from app.schema.state_conversation import FlightConversationState, FlightRequestPatch
from app.schema.chat_schema import ChatRequest
from datetime import date
from app.exception.flight_exceptions import (
    FlightExtractionOutputError,
    UserCorrectableFlightError,
)


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

        try:
            logger.info(
                "Extracting flight request",
                extra={
                    "event": "flight_request_extraction",
                    "conversation_id": state.conversation_id,
                },
            )
            context = self.context_factory.build(state)
            result = await Runner.run(self.agent, chat_request.message, context=context)
            patch = result.final_output
            if patch is None:
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

        except UserCorrectableFlightError as exc:
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
            logger.exception(
                "Flight request extraction failed",
                extra={
                    "event": "flight_request_extraction_failed",
                    "conversation_id": state.conversation_id,
                    "error": str(exc),
                },
            )
            raise

        return patch
