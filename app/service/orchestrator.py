import logging
from datetime import UTC, datetime

from langfuse import get_client

from app.exception.clarification import ClarificationResponse
from app.repositories.conversation_repository import (
    ConversationRepository,
)
from app.schema.chat_schema import (
    ChatRequest,
    ErrorResponse,
    FlightResultResponse,
    FlightSearchRequest,
)
from app.schema.state_conversation import FlightConversationState
from app.service.conversation_service.conversation_service import (
    FlightConversationService,
)
from app.service.flight_agent_service import FlightSelectionService

logger = logging.getLogger(__name__)


class FlightOrchestrator:
    def __init__(
        self,
        conversation_repository: ConversationRepository,
        conversation_service: FlightConversationService,
        selection_flights_service: FlightSelectionService,
    ):
        self.conversation_repository = conversation_repository
        self.conversation_service = conversation_service
        self.selection_flights_service = selection_flights_service

    async def handle_flight_request(
        self, chat_request: ChatRequest, conversation_id: str
    ) -> FlightSearchRequest | ClarificationResponse:
        logger.info(f"Handling flight request for conversation_id: {conversation_id}")
        langfuse = get_client()

        with langfuse.start_as_current_observation(
            as_type="chain", name="handle_flight_request", input=chat_request.message
        ) as span:
            state = await self.conversation_repository.get(conversation_id)
            if not state:
                logger.info(
                    f"No existing state found for conversation_id: {conversation_id}. Creating new state."
                )
                state = FlightConversationState(
                    conversation_id=conversation_id,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )

            (
                response,
                updated_state,
            ) = await self.conversation_service.process_chat_request(
                chat_request, state
            )
            await self.conversation_repository.save(updated_state)
            span.update(
                output=(
                    response.model_dump(mode="json")
                    if hasattr(response, "model_dump")
                    else str(response)
                )
            )

            return response

    async def run_flight_selection(
        self, search_request: FlightSearchRequest, conversation_id: str
    ) -> FlightResultResponse:
        langfuse = get_client()
        with langfuse.start_as_current_observation(
            as_type="chain",
            name="run_flight_selection",
            input=search_request.model_dump(mode="json"),
        ) as span:
            selection = await self.selection_flights_service.search_flights(
                search_request
            )
            if isinstance(selection, ClarificationResponse):
                return selection

            if isinstance(selection, ErrorResponse):
                return selection

            decision = await self.selection_flights_service.run_agent_selection(
                selection, conversation_id
            )
            result = self.selection_flights_service.build_decision_flights_response(
                decision, selection
            )
            await self.conversation_repository.delete(conversation_id)
            span.update(
                output=(
                    result.model_dump(mode="json")
                    if hasattr(result, "model_dump")
                    else str(result)
                )
            )
            return result
