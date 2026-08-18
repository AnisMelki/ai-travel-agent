import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.exception.clarification import ClarificationResponse, FlightErrorCode
from app.exception.flight_exceptions import (
    AirportNotFoundError,
    AmbiguityAirportError,
    FlightProviderError,
)
from app.hooks.flighs_run_hook import FlightRunHooks
from app.schema.chat_schema import FlightSearchRequest
from app.schema.flight_schema import FlightSearchResponse, FlightSearchResult
from app.service.flight_agent_service import FlightSelectionService


def _make_flight(flight_type: str) -> FlightSearchResult:
    return FlightSearchResult(
        flights=[],
        total_duration=100,
        layovers=None,
        price=200,
        type=flight_type,
    )


def _make_search_request() -> FlightSearchRequest:
    return FlightSearchRequest(
        origin="CDG",
        destination="LHR",
        departure_date=date(2026, 9, 1),
    )


def _make_flight_search_response() -> FlightSearchResponse:
    return FlightSearchResponse(
        results=[_make_flight("flight_a")],
        airline_reviews={},
    )


def _make_service(
    flight_search_orchestrator=None, agent_selection=None
) -> FlightSelectionService:
    return FlightSelectionService(
        flight_search_orchestrator=flight_search_orchestrator or AsyncMock(),
        agent_selection=agent_selection or object(),
    )


# ---------------------------------------------------------------------------
# search_flights
# ---------------------------------------------------------------------------


def test_search_flights_returns_orchestrator_result_on_success():
    search_request = _make_search_request()
    flight_search_response = _make_flight_search_response()
    orchestrator = AsyncMock()
    orchestrator.search_flight.return_value = flight_search_response
    service = _make_service(flight_search_orchestrator=orchestrator)

    result = asyncio.run(service.search_flights(search_request))

    assert result is flight_search_response
    orchestrator.search_flight.assert_awaited_once_with(search_request)


def test_search_flights_returns_clarification_response_for_airport_not_found():
    orchestrator = AsyncMock()
    orchestrator.search_flight.side_effect = AirportNotFoundError(
        "Paris", field="origin"
    )
    service = _make_service(flight_search_orchestrator=orchestrator)

    result = asyncio.run(service.search_flights(_make_search_request()))

    assert isinstance(result, ClarificationResponse)
    assert result.code == FlightErrorCode.AIRPORT_NOT_FOUND
    assert result.field == "origin"
    assert "Paris" in result.message


def test_search_flights_returns_clarification_response_for_ambiguous_airport():
    orchestrator = AsyncMock()
    orchestrator.search_flight.side_effect = AmbiguityAirportError(
        "Paris", ["CDG", "ORY"], field="origin"
    )
    service = _make_service(flight_search_orchestrator=orchestrator)

    result = asyncio.run(service.search_flights(_make_search_request()))

    assert isinstance(result, ClarificationResponse)
    assert result.code == FlightErrorCode.AIRPORT_AMBIGUOUS
    assert result.field == "origin"
    assert {option.value for option in result.options} == {"CDG", "ORY"}


def test_search_flights_propagates_non_user_correctable_errors():
    orchestrator = AsyncMock()
    orchestrator.search_flight.side_effect = FlightProviderError(
        "Apify flight search failed", provider="apify"
    )
    service = _make_service(flight_search_orchestrator=orchestrator)

    with pytest.raises(FlightProviderError, match="Apify flight search failed"):
        asyncio.run(service.search_flights(_make_search_request()))


def test_search_flights_propagates_unexpected_errors():
    orchestrator = AsyncMock()
    orchestrator.search_flight.side_effect = RuntimeError("boom")
    service = _make_service(flight_search_orchestrator=orchestrator)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(service.search_flights(_make_search_request()))


# ---------------------------------------------------------------------------
# run_agent_selection
# ---------------------------------------------------------------------------


def test_run_agent_selection_returns_final_output_on_success():
    flight_search_response = _make_flight_search_response()
    expected_decision = SimpleNamespace(selected_indexes=[0], reasoning="best")
    fake_agent = object()
    service = _make_service(agent_selection=fake_agent)

    with patch(
        "app.service.flight_agent_service.Runner.run",
        new=AsyncMock(return_value=SimpleNamespace(final_output=expected_decision)),
    ) as mock_run:
        result = asyncio.run(service.run_agent_selection(flight_search_response))

    assert result is expected_decision
    mock_run.assert_awaited_once()
    call_args = mock_run.call_args
    assert call_args.args == (fake_agent, flight_search_response.model_dump_json())
    assert isinstance(call_args.kwargs["hooks"], FlightRunHooks)


def test_run_agent_selection_reraises_unexpected_errors():
    flight_search_response = _make_flight_search_response()
    service = _make_service()

    with patch(
        "app.service.flight_agent_service.Runner.run",
        new=AsyncMock(side_effect=RuntimeError("agent run failed")),
    ):
        with pytest.raises(RuntimeError, match="agent run failed"):
            asyncio.run(service.run_agent_selection(flight_search_response))


# ---------------------------------------------------------------------------
# build_decision_flights_response
# ---------------------------------------------------------------------------


def test_build_decision_flights_response_returns_selected_flights():
    flight_a = _make_flight("flight_a")
    flight_b = _make_flight("flight_b")
    flight_c = _make_flight("flight_c")
    flight_search_response = SimpleNamespace(results=[flight_a, flight_b, flight_c])
    decision_flights = SimpleNamespace(
        selected_indexes=[0, 2], reasoning="best price and duration"
    )

    response = FlightSelectionService.build_decision_flights_response(
        decision_flights, flight_search_response
    )

    assert response.best_flights_selected == [flight_a, flight_c]
    assert response.reasoning == "best price and duration"


def test_build_decision_flights_response_preserves_selected_order_and_duplicates():
    flight_a = _make_flight("flight_a")
    flight_b = _make_flight("flight_b")
    flight_c = _make_flight("flight_c")
    flight_search_response = SimpleNamespace(results=[flight_a, flight_b, flight_c])
    decision_flights = SimpleNamespace(
        selected_indexes=[2, 0, 0], reasoning="duplicates allowed"
    )

    response = FlightSelectionService.build_decision_flights_response(
        decision_flights, flight_search_response
    )

    assert response.best_flights_selected == [flight_c, flight_a, flight_a]


def test_build_decision_flights_response_empty_selected_indexes():
    flight_search_response = SimpleNamespace(
        results=[_make_flight("flight_a"), _make_flight("flight_b")]
    )
    decision_flights = SimpleNamespace(selected_indexes=[], reasoning="no good options")

    response = FlightSelectionService.build_decision_flights_response(
        decision_flights, flight_search_response
    )

    assert response.best_flights_selected == []
    assert response.reasoning == "no good options"


def test_build_decision_flights_response_raises_when_decision_flights_is_none():
    flight_search_response = SimpleNamespace(results=[_make_flight("flight_a")])

    with pytest.raises(ValueError, match="must not be None"):
        FlightSelectionService.build_decision_flights_response(
            None, flight_search_response
        )


def test_build_decision_flights_response_raises_when_flight_search_response_is_none():
    decision_flights = SimpleNamespace(selected_indexes=[0], reasoning="ok")

    with pytest.raises(ValueError, match="must not be None"):
        FlightSelectionService.build_decision_flights_response(decision_flights, None)


def test_build_decision_flights_response_raises_when_both_are_none():
    with pytest.raises(ValueError, match="must not be None"):
        FlightSelectionService.build_decision_flights_response(None, None)


def test_build_decision_flights_response_raises_on_index_above_range():
    flight_search_response = SimpleNamespace(
        results=[_make_flight("flight_a"), _make_flight("flight_b")]
    )
    decision_flights = SimpleNamespace(selected_indexes=[0, 5], reasoning="oops")

    with pytest.raises(ValueError, match=r"\[5\]"):
        FlightSelectionService.build_decision_flights_response(
            decision_flights, flight_search_response
        )


def test_build_decision_flights_response_raises_on_negative_index():
    flight_search_response = SimpleNamespace(
        results=[_make_flight("flight_a"), _make_flight("flight_b")]
    )
    decision_flights = SimpleNamespace(selected_indexes=[-1], reasoning="oops")

    with pytest.raises(ValueError, match=r"\[-1\]"):
        FlightSelectionService.build_decision_flights_response(
            decision_flights, flight_search_response
        )


def test_build_decision_flights_response_raises_when_results_empty():
    flight_search_response = SimpleNamespace(results=[])
    decision_flights = SimpleNamespace(selected_indexes=[0], reasoning="oops")

    with pytest.raises(ValueError, match=r"\[0\]"):
        FlightSelectionService.build_decision_flights_response(
            decision_flights, flight_search_response
        )


def test_build_decision_flights_response_error_message_lists_all_out_of_range_indexes():
    flight_search_response = SimpleNamespace(results=[_make_flight("flight_a")])
    decision_flights = SimpleNamespace(selected_indexes=[1, 2, -1], reasoning="oops")

    with pytest.raises(ValueError, match=r"\[1, 2, -1\]"):
        FlightSelectionService.build_decision_flights_response(
            decision_flights, flight_search_response
        )
