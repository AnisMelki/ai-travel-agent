import logging
from typing import Annotated

from apify_client import ApifyClientAsync
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import get_settings
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.redis_conversation_repository import RedisConversationRepository
from app.schema.chat_schema import (
    ChatRequest,
    ClarificationResponse,
    FlightResultResponse,
)
from app.service.conversation_service.conversation_service import (
    FlightConversationService,
)
from app.service.conversation_service.extraction_request import (
    FlightRequestExtractionService,
)
from app.service.conversation_service.merger_completeness_state import (
    FlightRequestCompletenessChecker,
    FlightStateMerger,
)
from app.service.flight_agent_service import FlightSelectionService
from app.service.orchestrator import FlightOrchestrator
from app.tools.apify_airlines import AirlineReviewService
from app.tools.apify_flights import FlightSearchService
from app.tools.flight_selection import FlightSearchOrchestrator

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/flight", tags=["flight"])

settings = get_settings()


def get_conversation_repository(request: Request) -> ConversationRepository:
    return RedisConversationRepository(
        request.app.state.redis, settings.REDIS_CONVERSATION_TTL_SECONDS
    )


ConversationRepositoryDep = Annotated[
    ConversationRepository, Depends(get_conversation_repository)
]


def get_extractor_agent_service(request: Request) -> FlightRequestExtractionService:
    return FlightRequestExtractionService(request.app.state.flight_agent)


ExtractionServiceDep = Annotated[
    FlightRequestExtractionService, Depends(get_extractor_agent_service)
]


def get_apify_client(request: Request) -> ApifyClientAsync:
    return request.app.state.apify_client


ApifyClientDep = Annotated[ApifyClientAsync, Depends(get_apify_client)]


def get_flight_search_service(
    apify_client: ApifyClientDep,
) -> FlightSearchService:
    return FlightSearchService(apify_client)


FlightSearchServiceDep = Annotated[
    FlightSearchService, Depends(get_flight_search_service)
]


def get_airline_review_service(
    apify_client: ApifyClientDep,
) -> AirlineReviewService:
    return AirlineReviewService(apify_client)


AirlineReviewServiceDep = Annotated[
    AirlineReviewService, Depends(get_airline_review_service)
]


def get_flight_search_orchestrator(
    flight_service: FlightSearchServiceDep,
    airline_review_service: AirlineReviewServiceDep,
) -> FlightSearchOrchestrator:
    return FlightSearchOrchestrator(flight_service, airline_review_service)


FlightSearchOrchestratorDep = Annotated[
    FlightSearchOrchestrator, Depends(get_flight_search_orchestrator)
]


def get_flight_selection_service(
    request: Request,
    flight_search_orchestrator: FlightSearchOrchestratorDep,
) -> FlightSelectionService:
    return FlightSelectionService(
        flight_search_orchestrator, request.app.state.selection_agent
    )


FlightSelectionServiceDep = Annotated[
    FlightSelectionService, Depends(get_flight_selection_service)
]


def get_selection_agent_service(
    request: Request,
    flight_search_orchestrator: FlightSearchOrchestratorDep,
) -> FlightSelectionService:
    return FlightSelectionService(
        flight_search_orchestrator, request.app.state.selection_agent
    )


def get_conversation_service(
    extraction_service: ExtractionServiceDep,
) -> FlightConversationService:
    return FlightConversationService(
        extraction_service=extraction_service,
        state_merger=FlightStateMerger(),
        completeness_checker=FlightRequestCompletenessChecker(),
    )


ConversationServiceDep = Annotated[
    FlightConversationService, Depends(get_conversation_service)
]


def get_orchestrator(
    conversation_repository: ConversationRepositoryDep,
    conversation_service: ConversationServiceDep,
    selection_flights_service: FlightSelectionServiceDep,
) -> FlightOrchestrator:
    return FlightOrchestrator(
        conversation_repository=conversation_repository,
        conversation_service=conversation_service,
        selection_flights_service=selection_flights_service,
    )


OrchestratorDep = Annotated[FlightOrchestrator, Depends(get_orchestrator)]


@router.post("/search", response_model=FlightResultResponse)
async def search_flights(
    chat_request: ChatRequest,
    orchestrator: OrchestratorDep,
) -> FlightResultResponse:
    try:
        search_request, conversation_id = await orchestrator.handle_flight_request(
            chat_request
        )
        if isinstance(search_request, ClarificationResponse):
            return search_request
        return await orchestrator.run_flight_selection(search_request, conversation_id)

    except Exception as e:
        logger.exception("Error processing flight request")
        raise HTTPException(status_code=500, detail=str(e)) from e
