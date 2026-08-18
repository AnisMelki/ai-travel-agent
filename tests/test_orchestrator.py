import asyncio
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exception.clarification import ClarificationResponse
from app.repositories.conversation_repository import ConversationRepository
from app.schema.chat_schema import ChatRequest, ErrorResponse, FlightSearchRequest
from app.schema.flight_schema import (
    DecisionFlights,
    FlightSearchResponse,
    ResponseFlights,
)
from app.schema.state_conversation import ConversationStatus, FlightConversationState
from app.service.conversation_service.conversation_service import (
    FlightConversationService,
)
from app.service.flight_agent_service import FlightSelectionService
from app.service.orchestrator import FlightOrchestrator, get_or_create_conversation_id


def _make_state(**overrides) -> FlightConversationState:
    defaults = {
        "conversation_id": "conv-1",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return FlightConversationState(**defaults)


def _make_chat_request(conversation_id="conv-1", message="Hello") -> ChatRequest:
    return ChatRequest(conversation_id=conversation_id, message=message)


class _FakeChatRequest:
    """Duck-typed stand-in for the falsy-conversation_id branch; the real
    ChatRequest enforces min_length=1 and can never hold an empty id."""

    def __init__(self, conversation_id):
        self.conversation_id = conversation_id


def _make_repository(
    *,
    get_return=None,
    get_side_effect=None,
    save_side_effect=None,
    delete_side_effect=None,
) -> MagicMock:
    repository = MagicMock(spec=ConversationRepository)
    repository.get = AsyncMock(return_value=get_return, side_effect=get_side_effect)
    repository.save = AsyncMock(side_effect=save_side_effect)
    repository.delete = AsyncMock(side_effect=delete_side_effect)
    return repository


def _make_service(*, process_result=None, process_side_effect=None) -> MagicMock:
    service = MagicMock(spec=FlightConversationService)
    service.process_chat_request = AsyncMock(
        return_value=process_result, side_effect=process_side_effect
    )
    return service


def _make_selection_service(
    *,
    search_flights_return=None,
    search_flights_side_effect=None,
    run_agent_selection_return=None,
    run_agent_selection_side_effect=None,
    build_decision_flights_response_return=None,
) -> MagicMock:
    """`FlightOrchestrator.run_flight_selection`'s collaborator; only the
    `handle_flight_request` tests below use this with no arguments (not
    exercised, just required by the ctor)."""
    service = MagicMock(spec=FlightSelectionService)
    service.search_flights = AsyncMock(
        return_value=search_flights_return, side_effect=search_flights_side_effect
    )
    service.run_agent_selection = AsyncMock(
        return_value=run_agent_selection_return,
        side_effect=run_agent_selection_side_effect,
    )
    service.build_decision_flights_response = MagicMock(
        return_value=build_decision_flights_response_return
    )
    return service


def _make_search_request() -> FlightSearchRequest:
    return FlightSearchRequest(
        origin="CDG", destination="LHR", departure_date=date(2026, 9, 1)
    )


def _make_flight_search_response() -> FlightSearchResponse:
    return FlightSearchResponse(
        results=[],
        airline_reviews={},
    )


# ---------------------------------------------------------------------------
# get_or_create_conversation_id
# ---------------------------------------------------------------------------


def test_get_or_create_conversation_id_returns_existing_id_when_present():
    assert get_or_create_conversation_id(_make_chat_request("conv-99")) == "conv-99"


def test_get_or_create_conversation_id_generates_uuid_when_empty():
    generated = get_or_create_conversation_id(_FakeChatRequest(conversation_id=""))
    assert generated
    assert generated != ""


def test_get_or_create_conversation_id_generates_uuid_when_none():
    generated = get_or_create_conversation_id(_FakeChatRequest(conversation_id=None))
    assert generated


# ---------------------------------------------------------------------------
# new vs. existing state
# ---------------------------------------------------------------------------


def test_creates_new_state_with_defaults_when_none_found():
    updated_state = _make_state(origin="Paris")
    response = ClarificationResponse(message="Which date?")
    repository = _make_repository(get_return=None)
    service = _make_service(process_result=(response, updated_state))
    orchestrator = FlightOrchestrator(repository, service, _make_selection_service())

    result, conversation_id = asyncio.run(
        orchestrator.handle_flight_request(_make_chat_request(conversation_id="conv-1"))
    )

    assert result is response
    assert conversation_id == "conv-1"
    repository.get.assert_awaited_once_with("conv-1")

    passed_state = service.process_chat_request.await_args.args[1]
    assert passed_state.conversation_id == "conv-1"
    assert passed_state.status == ConversationStatus.COLLECTING
    assert passed_state.version == 0
    assert passed_state.pending_clarification is None


def test_reuses_existing_state_object_when_found():
    existing_state = _make_state(conversation_id="conv-2", origin="Paris")
    updated_state = _make_state(conversation_id="conv-2", destination="London")
    response = ClarificationResponse(message="Which date?")
    repository = _make_repository(get_return=existing_state)
    service = _make_service(process_result=(response, updated_state))
    orchestrator = FlightOrchestrator(repository, service, _make_selection_service())

    result, conversation_id = asyncio.run(
        orchestrator.handle_flight_request(_make_chat_request(conversation_id="conv-2"))
    )

    assert result is response
    assert conversation_id == "conv-2"
    passed_state = service.process_chat_request.await_args.args[1]
    assert passed_state is existing_state


def test_generates_and_reuses_a_fresh_conversation_id_end_to_end():
    repository = _make_repository(get_return=None)
    response = ClarificationResponse(message="ok")
    captured = {}

    async def fake_process(chat_request, state):
        captured["state"] = state
        return response, state

    service = _make_service()
    service.process_chat_request.side_effect = fake_process
    orchestrator = FlightOrchestrator(repository, service, _make_selection_service())

    asyncio.run(
        orchestrator.handle_flight_request(_FakeChatRequest(conversation_id=""))
    )

    generated_id = captured["state"].conversation_id
    assert generated_id
    repository.get.assert_awaited_once_with(generated_id)


# ---------------------------------------------------------------------------
# exact updated_state persistence
# ---------------------------------------------------------------------------


def test_saves_the_exact_updated_state_returned_by_service():
    updated_state = _make_state(destination="Berlin")
    response = FlightSearchRequest(
        origin="CDG", destination="LHR", departure_date=date(2026, 9, 1)
    )
    repository = _make_repository(get_return=_make_state())
    service = _make_service(process_result=(response, updated_state))
    orchestrator = FlightOrchestrator(repository, service, _make_selection_service())

    asyncio.run(orchestrator.handle_flight_request(_make_chat_request()))

    repository.save.assert_awaited_once_with(updated_state)


# ---------------------------------------------------------------------------
# call ordering / skipped calls on failure
# ---------------------------------------------------------------------------


def test_repository_get_failure_propagates_and_skips_service_and_save():
    repository = _make_repository(get_side_effect=RuntimeError("redis down"))
    service = _make_service()
    orchestrator = FlightOrchestrator(repository, service, _make_selection_service())

    with pytest.raises(RuntimeError, match="redis down"):
        asyncio.run(orchestrator.handle_flight_request(_make_chat_request()))

    service.process_chat_request.assert_not_awaited()
    repository.save.assert_not_awaited()


def test_conversation_service_failure_propagates_and_skips_save():
    repository = _make_repository(get_return=_make_state())
    service = _make_service(process_side_effect=ValueError("bad extraction"))
    orchestrator = FlightOrchestrator(repository, service, _make_selection_service())

    with pytest.raises(ValueError, match="bad extraction"):
        asyncio.run(orchestrator.handle_flight_request(_make_chat_request()))

    repository.get.assert_awaited_once()
    repository.save.assert_not_awaited()


def test_repository_save_failure_propagates_after_service_already_ran():
    updated_state = _make_state()
    response = ClarificationResponse(message="hi")
    repository = _make_repository(
        get_return=_make_state(), save_side_effect=RuntimeError("save failed")
    )
    service = _make_service(process_result=(response, updated_state))
    orchestrator = FlightOrchestrator(repository, service, _make_selection_service())

    with pytest.raises(RuntimeError, match="save failed"):
        asyncio.run(orchestrator.handle_flight_request(_make_chat_request()))

    service.process_chat_request.assert_awaited_once()
    repository.save.assert_awaited_once_with(updated_state)


def test_calls_happen_in_get_then_process_then_save_order():
    call_order = []

    async def fake_get(conversation_id):
        call_order.append("get")
        return _make_state()

    async def fake_process(chat_request, state):
        call_order.append("process")
        return ClarificationResponse(message="ok"), state

    async def fake_save(state):
        call_order.append("save")

    repository = _make_repository()
    repository.get.side_effect = fake_get
    repository.save.side_effect = fake_save
    service = _make_service()
    service.process_chat_request.side_effect = fake_process
    orchestrator = FlightOrchestrator(repository, service, _make_selection_service())

    asyncio.run(orchestrator.handle_flight_request(_make_chat_request()))

    assert call_order == ["get", "process", "save"]


# ---------------------------------------------------------------------------
# run_flight_selection
# ---------------------------------------------------------------------------


def test_run_flight_selection_returns_clarification_response_without_further_calls():
    clarification = ClarificationResponse(message="Which airport?", field="origin")
    selection_service = _make_selection_service(search_flights_return=clarification)
    repository = _make_repository()
    orchestrator = FlightOrchestrator(repository, _make_service(), selection_service)

    result = asyncio.run(
        orchestrator.run_flight_selection(_make_search_request(), "conv-1")
    )

    assert result is clarification
    selection_service.run_agent_selection.assert_not_awaited()
    selection_service.build_decision_flights_response.assert_not_called()
    repository.delete.assert_not_awaited()


def test_run_flight_selection_returns_error_response_without_further_calls():
    # FlightSelectionService.search_flights never returns ErrorResponse today,
    # but the orchestrator still branches on it defensively — tested here by
    # mocking the collaborator directly, independent of that real behavior.
    error = ErrorResponse(message="boom", error_code="provider_error", retryable=True)
    selection_service = _make_selection_service(search_flights_return=error)
    repository = _make_repository()
    orchestrator = FlightOrchestrator(repository, _make_service(), selection_service)

    result = asyncio.run(
        orchestrator.run_flight_selection(_make_search_request(), "conv-1")
    )

    assert result is error
    selection_service.run_agent_selection.assert_not_awaited()
    selection_service.build_decision_flights_response.assert_not_called()
    repository.delete.assert_not_awaited()


def test_run_flight_selection_returns_built_result_and_deletes_conversation_on_success():
    search_response = _make_flight_search_response()
    decision = DecisionFlights(selected_indexes=[], reasoning="no flights matched")
    built_result = ResponseFlights(reasoning="best price and duration")
    selection_service = _make_selection_service(
        search_flights_return=search_response,
        run_agent_selection_return=decision,
        build_decision_flights_response_return=built_result,
    )
    repository = _make_repository()
    orchestrator = FlightOrchestrator(repository, _make_service(), selection_service)

    result = asyncio.run(
        orchestrator.run_flight_selection(_make_search_request(), "conv-77")
    )

    assert result is built_result
    selection_service.run_agent_selection.assert_awaited_once_with(search_response)
    selection_service.build_decision_flights_response.assert_called_once_with(
        decision, search_response
    )
    repository.delete.assert_awaited_once_with("conv-77")


def test_run_flight_selection_calls_happen_in_search_then_select_then_build_then_delete_order():
    call_order = []
    search_response = _make_flight_search_response()
    decision = DecisionFlights(selected_indexes=[], reasoning="no flights matched")
    built_result = ResponseFlights(reasoning="ok")

    async def fake_search_flights(search_request):
        call_order.append("search")
        return search_response

    async def fake_run_agent_selection(flight_search_response):
        call_order.append("select")
        return decision

    def fake_build_decision_flights_response(decision_flights, flight_search_response):
        call_order.append("build")
        return built_result

    async def fake_delete(conversation_id):
        call_order.append("delete")

    selection_service = _make_selection_service()
    selection_service.search_flights.side_effect = fake_search_flights
    selection_service.run_agent_selection.side_effect = fake_run_agent_selection
    selection_service.build_decision_flights_response.side_effect = (
        fake_build_decision_flights_response
    )
    repository = _make_repository()
    repository.delete.side_effect = fake_delete
    orchestrator = FlightOrchestrator(repository, _make_service(), selection_service)

    asyncio.run(orchestrator.run_flight_selection(_make_search_request(), "conv-1"))

    assert call_order == ["search", "select", "build", "delete"]


def test_run_flight_selection_propagates_search_flights_exception_and_skips_rest():
    selection_service = _make_selection_service(
        search_flights_side_effect=RuntimeError("provider down")
    )
    repository = _make_repository()
    orchestrator = FlightOrchestrator(repository, _make_service(), selection_service)

    with pytest.raises(RuntimeError, match="provider down"):
        asyncio.run(orchestrator.run_flight_selection(_make_search_request(), "conv-1"))

    selection_service.run_agent_selection.assert_not_awaited()
    selection_service.build_decision_flights_response.assert_not_called()
    repository.delete.assert_not_awaited()


def test_run_flight_selection_propagates_run_agent_selection_exception_and_skips_rest():
    search_response = _make_flight_search_response()
    selection_service = _make_selection_service(
        search_flights_return=search_response,
        run_agent_selection_side_effect=RuntimeError("agent failed"),
    )
    repository = _make_repository()
    orchestrator = FlightOrchestrator(repository, _make_service(), selection_service)

    with pytest.raises(RuntimeError, match="agent failed"):
        asyncio.run(orchestrator.run_flight_selection(_make_search_request(), "conv-1"))

    selection_service.build_decision_flights_response.assert_not_called()
    repository.delete.assert_not_awaited()


def test_run_flight_selection_propagates_delete_exception_after_result_was_built():
    search_response = _make_flight_search_response()
    decision = DecisionFlights(selected_indexes=[], reasoning="no flights matched")
    built_result = ResponseFlights(reasoning="ok")
    selection_service = _make_selection_service(
        search_flights_return=search_response,
        run_agent_selection_return=decision,
        build_decision_flights_response_return=built_result,
    )
    repository = _make_repository(delete_side_effect=RuntimeError("delete failed"))
    orchestrator = FlightOrchestrator(repository, _make_service(), selection_service)

    with pytest.raises(RuntimeError, match="delete failed"):
        asyncio.run(orchestrator.run_flight_selection(_make_search_request(), "conv-1"))

    selection_service.build_decision_flights_response.assert_called_once()
