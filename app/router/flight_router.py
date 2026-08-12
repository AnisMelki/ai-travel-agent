from apify_client import ApifyClientAsync
from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.config import get_settings
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.redis_conversation_repository import RedisConversationRepository
from app.service.conversation_service.conversation_service import (
    FlightConversationService,
)
from app.schema.chat_schema import ChatRequest, FlightResultResponse

from app.schema.chat_schema import ClarificationResponse
from app.schema.chat_schema import FlightSearchRequest
import logging
from app.service.conversation_service.extraction_request import (
    FlightRequestExtractionService,
)
from app.service.conversation_service.merger_completeness_state import (
    FlightRequestCompletenessChecker,
    FlightStateMerger,
)
from app.tools.apify_flights import FlightSearchService
from app.tools.apify_airlines import AirlineReviewService
from app.tools.flight_selection import FlightSearchOrchestrator
from app.service.flight_agent_service import FlightSelectionService
from app.service.orchestrator import FlightOrchestrator

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/flight", tags=["flight"])

settings = get_settings()


def get_conversation_repository(request: Request) -> ConversationRepository:
    return RedisConversationRepository(
        request.app.state.redis, settings.REDIS_CONVERSATION_TTL_SECONDS
    )


def get_extractor_agent_service(request: Request) -> FlightRequestExtractionService:
    return FlightRequestExtractionService(request.app.state.flight_agent)


def get_apify_client(request: Request) -> ApifyClientAsync:
    return request.app.state.apify_client


def get_flight_search_service(
    apify_client: ApifyClientAsync = Depends(get_apify_client),
) -> FlightSearchService:
    return FlightSearchService(apify_client)


def get_airline_review_service(
    apify_client: ApifyClientAsync = Depends(get_apify_client),
) -> AirlineReviewService:
    return AirlineReviewService(apify_client)


def get_flight_search_orchestrator(
    flight_service: FlightSearchService = Depends(get_flight_search_service),
    airline_review_service: AirlineReviewService = Depends(get_airline_review_service),
) -> FlightSearchOrchestrator:
    return FlightSearchOrchestrator(flight_service, airline_review_service)


def get_flight_selection_service(
    flight_search_orchestrator: FlightSearchOrchestrator = Depends(
        get_flight_search_orchestrator
    ),
    request: Request = None,
) -> FlightSelectionService:
    return FlightSelectionService(
        flight_search_orchestrator, request.app.state.selection_agent
    )


def get_selection_agent_service(
    request: Request,
    flight_search_orchestrator: FlightSearchOrchestrator = Depends(
        get_flight_search_orchestrator
    ),
) -> FlightSelectionService:
    return FlightSelectionService(
        flight_search_orchestrator, request.app.state.selection_agent
    )


def get_conversation_service(
    extraction_service: FlightRequestExtractionService = Depends(
        get_extractor_agent_service
    ),
) -> FlightConversationService:
    return FlightConversationService(
        extraction_service=extraction_service,
        state_merger=FlightStateMerger(),
        completeness_checker=FlightRequestCompletenessChecker(),
    )


def get_orchestrator(
    conversation_repository: ConversationRepository = Depends(
        get_conversation_repository
    ),
    conversation_service: FlightConversationService = Depends(get_conversation_service),
    selection_flights_service: FlightSelectionService = Depends(
        get_flight_selection_service
    ),
) -> FlightOrchestrator:
    return FlightOrchestrator(
        conversation_repository=conversation_repository,
        conversation_service=conversation_service,
        selection_flights_service=selection_flights_service,
    )


@router.post("/search", response_model=FlightResultResponse)
async def search_flights(
    chat_request: ChatRequest,
    orchestrator: FlightOrchestrator = Depends(get_orchestrator),
) -> FlightResultResponse:
    try:
        search_request, conversation_id = await orchestrator.handle_flight_request(
            chat_request
        )
        if isinstance(search_request, ClarificationResponse):
            return search_request
        return await orchestrator.run_flight_selection(search_request, conversation_id)

    except Exception as e:
        logger.exception(f"Error processing flight request: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
