import asyncio
from datetime import date, datetime

import pytest

from app.exception.clarification import ClarificationBuilder, ClarificationResponse
from app.exception.flight_exceptions import AirportNotFoundError, AmbiguityAirportError
from app.schema.chat_schema import ChatRequest, FlightSearchRequest
from app.schema.state_conversation import (
    ConversationStatus,
    FlightConversationState,
    FlightRequestPatch,
    PendingClarification,
)
from app.service.conversation_service.conversation_service import (
    FlightConversationService,
)


def _make_state(**overrides) -> FlightConversationState:
    defaults = dict(
        conversation_id="conv-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return FlightConversationState(**defaults)


class FakeExtractionService:
    def __init__(self, patch: FlightRequestPatch):
        self._patch = patch

    async def extract_flight_request(self, chat_request, state):
        return self._patch


class FakeStateMerger:
    def __init__(self, merged_state: FlightConversationState):
        self._merged_state = merged_state

    def merge(self, current_state, patch):
        return self._merged_state


class FakeCompletenessChecker:
    def __init__(self, is_complete: bool, missing_fields: list[str] | None = None):
        self._is_complete = is_complete
        self._missing_fields = missing_fields or []

    def is_complete(self, state):
        return self._is_complete

    def missing_fields(self, state):
        return self._missing_fields


class FakeAsyncSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _build_service(
    *,
    is_complete: bool,
    missing_fields: list[str] | None = None,
    merged_state: FlightConversationState | None = None,
    airport_resolution_service_factory=None,
) -> FlightConversationService:
    merged_state = merged_state or _make_state(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
    )
    kwargs = {}
    if airport_resolution_service_factory is not None:
        kwargs["session_factory"] = lambda: FakeAsyncSession()
        kwargs["airport_resolution_service_factory"] = (
            airport_resolution_service_factory
        )
    return FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(merged_state),
        completeness_checker=FakeCompletenessChecker(is_complete, missing_fields),
        **kwargs,
    )


def test_returns_clarification_when_state_incomplete():
    service = _build_service(is_complete=False, missing_fields=["origin"])
    state = _make_state()
    chat_request = ChatRequest(conversation_id="conv-1", message="hello")

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert isinstance(response, ClarificationResponse)
    assert response.missing_fields == ["origin"]
    assert response.field == "origin"
    assert updated_state.origin == "paris"


def test_returns_flight_search_request_when_airport_resolution_succeeds():
    class FakeAirportResolutionService:
        async def search_city(self, city: str, *, field: str | None = None) -> str:
            return "CDG" if city == "paris" else "LHR"

    service = _build_service(
        is_complete=True,
        airport_resolution_service_factory=lambda session: FakeAirportResolutionService(),
    )

    chat_request = ChatRequest(conversation_id="conv-1", message="hello")
    state = _make_state()

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert isinstance(response, FlightSearchRequest)
    assert response.origin == "CDG"
    assert response.destination == "LHR"
    assert updated_state.origin_code == "CDG"
    assert updated_state.destination_code == "LHR"
    assert updated_state.status == ConversationStatus.READY


def test_returns_clarification_when_airport_not_found():
    class FakeAirportResolutionService:
        async def search_city(self, city: str, *, field: str | None = None) -> str:
            raise AirportNotFoundError(city, field=field)

    service = _build_service(
        is_complete=True,
        airport_resolution_service_factory=lambda session: FakeAirportResolutionService(),
    )

    chat_request = ChatRequest(conversation_id="conv-1", message="hello")
    state = _make_state()

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert isinstance(response, ClarificationResponse)
    assert response.code == "airport_not_found"


def test_returns_clarification_when_airport_ambiguous():
    class FakeAirportResolutionService:
        async def search_city(self, city: str, *, field: str | None = None) -> str:
            raise AmbiguityAirportError(city, ["LHR", "LGW", "LCY"], field=field)

    service = _build_service(
        is_complete=True,
        airport_resolution_service_factory=lambda session: FakeAirportResolutionService(),
    )

    chat_request = ChatRequest(conversation_id="conv-1", message="hello")
    state = _make_state()

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert isinstance(response, ClarificationResponse)
    assert response.code == "airport_ambiguous"


def test_resolve_airport_codes_uses_injected_session_and_factory():
    created_sessions = []

    class TrackingAsyncSession:
        async def __aenter__(self):
            created_sessions.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeAirportResolutionService:
        async def search_city(self, city: str, *, field: str | None = None) -> str:
            return "CDG" if city == "paris" else "LHR"

    factory_calls = []

    def factory(session):
        factory_calls.append(session)
        return FakeAirportResolutionService()

    merged_state = _make_state(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
    )
    service = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(merged_state),
        completeness_checker=FakeCompletenessChecker(True),
        session_factory=lambda: TrackingAsyncSession(),
        airport_resolution_service_factory=factory,
    )

    chat_request = ChatRequest(conversation_id="conv-1", message="hello")
    state = _make_state()

    asyncio.run(service.process_chat_request(chat_request, state))

    assert len(created_sessions) == 1
    assert factory_calls == [created_sessions[0]]


def test_flight_search_request_preserves_dates_from_state():
    merged_state = _make_state(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
        return_date=date(2026, 9, 10),
    )

    class FakeAirportResolutionService:
        async def search_city(self, city: str, *, field: str | None = None) -> str:
            return "CDG" if city == "paris" else "LHR"

    service = _build_service(
        is_complete=True,
        merged_state=merged_state,
        airport_resolution_service_factory=lambda session: FakeAirportResolutionService(),
    )

    chat_request = ChatRequest(conversation_id="conv-1", message="hello")
    state = _make_state()

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert updated_state.departure_date == date(2026, 9, 1)
    assert updated_state.return_date == date(2026, 9, 10)


def test_extraction_service_receives_original_state_and_request():
    received = {}

    class SpyExtractionService:
        async def extract_flight_request(self, chat_request, state):
            received["chat_request"] = chat_request
            received["state"] = state
            return FlightRequestPatch()

    merged_state = _make_state(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
    )
    service = FlightConversationService(
        extraction_service=SpyExtractionService(),
        state_merger=FakeStateMerger(merged_state),
        completeness_checker=FakeCompletenessChecker(False, ["origin"]),
    )

    chat_request = ChatRequest(conversation_id="conv-1", message="hello")
    state = _make_state(conversation_id="conv-1")

    asyncio.run(service.process_chat_request(chat_request, state))

    assert received["chat_request"] is chat_request
    # process_chat_request copies the state (via model_copy) to set status
    # to COLLECTING before extraction, so the extraction service receives an
    # equal-by-value state rather than the exact same instance.
    assert received["state"] == state.model_copy(
        update={"status": ConversationStatus.COLLECTING}
    )


def test_unhandled_exception_from_airport_resolution_propagates():
    class FakeAirportResolutionService:
        async def search_city(self, city: str, *, field: str | None = None) -> str:
            raise RuntimeError("unexpected failure")

    service = _build_service(
        is_complete=True,
        airport_resolution_service_factory=lambda session: FakeAirportResolutionService(),
    )

    chat_request = ChatRequest(conversation_id="conv-1", message="hello")
    state = _make_state()

    with pytest.raises(RuntimeError, match="unexpected failure"):
        asyncio.run(service.process_chat_request(chat_request, state))


def test_init_stores_extraction_service_state_merger_and_completeness_checker():
    extraction_service = FakeExtractionService(FlightRequestPatch())
    state_merger = FakeStateMerger(_make_state())
    completeness_checker = FakeCompletenessChecker(True)

    service = FlightConversationService(
        extraction_service=extraction_service,
        state_merger=state_merger,
        completeness_checker=completeness_checker,
    )

    assert service.extraction_service is extraction_service
    assert service.state_merger is state_merger
    assert service.completeness_checker is completeness_checker


def test_init_uses_default_session_factory_when_not_provided():
    from app.database.session import SessionLocal

    service = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(True),
    )

    assert service._session_factory is SessionLocal


def test_init_uses_default_airport_resolution_service_factory_when_not_provided():
    from app.service.conversation_service.conversation_service import (
        _default_airport_resolution_service_factory,
    )

    service = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(True),
    )

    assert (
        service._airport_resolution_service_factory
        is _default_airport_resolution_service_factory
    )


def test_init_stores_custom_session_factory_when_provided():
    def custom_session_factory():
        return FakeAsyncSession()

    service = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(True),
        session_factory=custom_session_factory,
    )

    assert service._session_factory is custom_session_factory


def test_init_stores_custom_airport_resolution_service_factory_when_provided():
    def custom_factory(session):
        return object()

    service = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(True),
        airport_resolution_service_factory=custom_factory,
    )

    assert service._airport_resolution_service_factory is custom_factory


def test_init_creates_error_translator_instance():
    from app.exception.flight_exceptions import FlightErrorTranslator

    service = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(True),
    )

    assert isinstance(service._error_translator, FlightErrorTranslator)


def test_init_creates_clarification_builder_instance():
    service = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(True),
    )

    assert isinstance(service._clarification_builder, ClarificationBuilder)


def test_init_creates_independent_instances_across_multiple_services():
    service_one = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(True),
    )
    service_two = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(False),
    )

    assert service_one._error_translator is not service_two._error_translator
    assert service_one._clarification_builder is not service_two._clarification_builder


# ---------------------------------------------------------------------------
# pending_clarification dispatch / resume behavior
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["missing_field", "airport_not_found"])
def test_pending_clarification_missing_field_or_airport_not_found_resumes_extraction(
    reason,
):
    service = _build_service(is_complete=False, missing_fields=["destination"])
    pending = PendingClarification(reason=reason, field_name="origin")
    state = _make_state(
        pending_clarification=pending, status=ConversationStatus.RESOLVING_AIRPORTS
    )
    chat_request = ChatRequest(conversation_id="conv-1", message="London")

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert isinstance(response, ClarificationResponse)
    assert response.missing_fields == ["destination"]
    assert updated_state.pending_clarification is not None
    assert updated_state.pending_clarification.field_name == "destination"


def test_pending_ambiguous_airport_dispatches_to_ambiguous_handler():
    service = _build_service(is_complete=True)
    pending = PendingClarification(
        reason="ambiguous_airport",
        field_name="origin",
        allowed_airport_codes=["ORY", "CDG"],
    )
    state = _make_state(
        pending_clarification=pending, status=ConversationStatus.RESOLVING_AIRPORTS
    )
    chat_request = ChatRequest(conversation_id="conv-1", message="XXX")

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    # Invalid choice: pending clarification kept, same state instance returned.
    assert isinstance(response, ClarificationResponse)
    assert response.code == "airport_ambiguous"
    assert updated_state is state
    assert updated_state.pending_clarification == pending


def test_pending_ambiguous_airport_valid_choice_normalizes_case_and_whitespace():
    class FakeAirportResolutionService:
        async def search_city(self, city, *, field=None):
            assert field == "destination"
            return "LHR"

    service = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(True),
        session_factory=lambda: FakeAsyncSession(),
        airport_resolution_service_factory=lambda session: FakeAirportResolutionService(),
    )

    pending = PendingClarification(
        reason="ambiguous_airport",
        field_name="origin",
        allowed_airport_codes=["ORY", "CDG"],
    )
    state = _make_state(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
        pending_clarification=pending,
        status=ConversationStatus.RESOLVING_AIRPORTS,
    )
    chat_request = ChatRequest(conversation_id="conv-1", message="  cdg  ")

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert isinstance(response, FlightSearchRequest)
    assert response.origin == "CDG"
    assert response.destination == "LHR"
    assert updated_state.origin_code == "CDG"
    assert updated_state.pending_clarification is None
    assert updated_state.status == ConversationStatus.READY


def test_pending_ambiguous_airport_valid_choice_for_destination_field():
    class FakeAirportResolutionService:
        async def search_city(self, city, *, field=None):
            assert field == "origin"
            return "CDG"

    service = FlightConversationService(
        extraction_service=FakeExtractionService(FlightRequestPatch()),
        state_merger=FakeStateMerger(_make_state()),
        completeness_checker=FakeCompletenessChecker(True),
        session_factory=lambda: FakeAsyncSession(),
        airport_resolution_service_factory=lambda session: FakeAirportResolutionService(),
    )

    pending = PendingClarification(
        reason="ambiguous_airport",
        field_name="destination",
        allowed_airport_codes=["LHR", "LGW"],
    )
    state = _make_state(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
        pending_clarification=pending,
        status=ConversationStatus.RESOLVING_AIRPORTS,
    )
    chat_request = ChatRequest(conversation_id="conv-1", message="LGW")

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert isinstance(response, FlightSearchRequest)
    assert response.destination == "LGW"
    assert updated_state.destination_code == "LGW"
    assert updated_state.pending_clarification is None


# ---------------------------------------------------------------------------
# TranslatedError -> PendingClarification field/reason mapping (regression
# coverage for the AttributeError bugs fixed in _build_pending_clarification_from_error)
# ---------------------------------------------------------------------------


def test_ambiguous_airport_error_populates_pending_clarification_correctly():
    class FakeAirportResolutionService:
        async def search_city(self, city, *, field=None):
            if field == "origin":
                raise AmbiguityAirportError(city, ["ORY", "CDG"], field="origin")
            return "LHR"

    service = _build_service(
        is_complete=True,
        airport_resolution_service_factory=lambda session: FakeAirportResolutionService(),
    )
    chat_request = ChatRequest(conversation_id="conv-1", message="hello")
    state = _make_state()

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert isinstance(response, ClarificationResponse)
    assert response.code == "airport_ambiguous"
    pending = updated_state.pending_clarification
    assert pending is not None
    assert pending.reason == "ambiguous_airport"
    assert pending.field_name == "origin"
    assert pending.allowed_airport_codes == ["ORY", "CDG"]
    assert updated_state.status == ConversationStatus.RESOLVING_AIRPORTS


def test_airport_not_found_error_populates_pending_clarification_correctly():
    class FakeAirportResolutionService:
        async def search_city(self, city, *, field=None):
            if field == "destination":
                raise AirportNotFoundError(city, field="destination")
            return "CDG"

    service = _build_service(
        is_complete=True,
        airport_resolution_service_factory=lambda session: FakeAirportResolutionService(),
    )
    chat_request = ChatRequest(conversation_id="conv-1", message="hello")
    state = _make_state()

    response, updated_state = asyncio.run(
        service.process_chat_request(chat_request, state)
    )

    assert isinstance(response, ClarificationResponse)
    assert response.code == "airport_not_found"
    pending = updated_state.pending_clarification
    assert pending is not None
    assert pending.reason == "airport_not_found"
    assert pending.field_name == "destination"
    assert pending.allowed_airport_codes == []
