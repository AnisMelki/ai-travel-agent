import logging
from datetime import datetime, timezone
import uuid

from app.service.conversation_service.conversation_service import (
    FlightConversationService,
)
from app.repositories.conversation_repository import (
    ConversationRepository,
)
from app.schema.chat_schema import (
    ChatRequest,
    FlightResultResponse,
    FlightSearchRequest,
    ErrorResponse,
)
from app.schema.state_conversation import FlightConversationState
from app.exception.clarification import ClarificationResponse
from app.service.flight_agent_service import FlightSelectionService

logger = logging.getLogger(__name__)


def get_or_create_conversation_id(request: ChatRequest) -> str:
    """
    Generate a unique conversation ID based on the user ID and the current timestamp.
    """
    return request.conversation_id or str(uuid.uuid4())


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
        self, chat_request: ChatRequest
    ) -> tuple[FlightSearchRequest | ClarificationResponse, str]:
        conversation_id = get_or_create_conversation_id(chat_request)
        logger.info(f"Handling flight request for conversation_id: {conversation_id}")
        state = await self.conversation_repository.get(conversation_id)
        if not state:
            logger.info(
                f"No existing state found for conversation_id: {conversation_id}. Creating new state."
            )
            state = FlightConversationState(
                conversation_id=conversation_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        response, updated_state = await self.conversation_service.process_chat_request(
            chat_request, state
        )
        await self.conversation_repository.save(updated_state)
        return response, conversation_id

    async def run_flight_selection(
        self, search_request: FlightSearchRequest, conversation_id: str
    ) -> FlightResultResponse:
        selection = await self.selection_flights_service.search_flights(search_request)
        if isinstance(selection, ClarificationResponse):
            return selection

        if isinstance(selection, ErrorResponse):
            return selection

        decision = await self.selection_flights_service.run_agent_selection(selection)
        result = self.selection_flights_service.build_decision_flights_response(
            decision, selection
        )
        await self.conversation_repository.delete(conversation_id)
        return result
