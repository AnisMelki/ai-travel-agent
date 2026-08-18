import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exception.flight_exceptions import EmptyFlightSearch
from app.schema.airline_reviews_schema import AirlineSummary
from app.schema.chat_schema import FlightSearchRequest
from app.schema.flight_schema import FlightSearchOutcome, FlightSearchResult
from app.tools.flight_selection import FlightSearchOrchestrator


def _make_flight(flight_type: str) -> FlightSearchResult:
    return FlightSearchResult(
        flights=[],
        total_duration=100,
        layovers=None,
        price=200,
        type=flight_type,
    )


def _make_search_request(
    *,
    origin="TUN",
    destination="YUL",
    departure_date=date(2026, 9, 1),
    return_date=None,
) -> FlightSearchRequest:
    return FlightSearchRequest(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
    )


def _make_flight_service(*, return_value=None, side_effect=None) -> MagicMock:
    flight_service = MagicMock()
    flight_service.search_flight = AsyncMock(
        return_value=return_value, side_effect=side_effect
    )
    return flight_service


def _make_airline_review_service(*, return_value=None) -> MagicMock:
    airline_review_service = MagicMock()
    airline_review_service.get_airline_summaries = AsyncMock(
        return_value=return_value if return_value is not None else {}
    )
    return airline_review_service


def test_search_flight_returns_response_with_airline_reviews():
    flight_a = _make_flight("flight_a")
    outcome = FlightSearchOutcome(flights=[flight_a], airline_names={"Example Air"})
    airline_summaries = {
        "Example Air": AirlineSummary(
            average_rating=8,
            average_verification_rate=100,
            total_comments=["Good"],
        )
    }
    flight_service = _make_flight_service(return_value=outcome)
    airline_review_service = _make_airline_review_service(
        return_value=airline_summaries
    )
    orchestrator = FlightSearchOrchestrator(flight_service, airline_review_service)
    search_request = _make_search_request(return_date=date(2026, 9, 10))

    response = asyncio.run(orchestrator.search_flight(search_request))

    assert response.results == [flight_a]
    assert response.airline_reviews["Example Air"].average_rating == 8
    flight_service.search_flight.assert_awaited_once_with(
        origin="TUN",
        destination="YUL",
        departure_date="2026-09-01",
        return_date="2026-09-10",
    )
    airline_review_service.get_airline_summaries.assert_awaited_once_with(
        airline_names={"Example Air"}, max_reviews=10
    )


def test_search_flight_converts_dates_to_iso_strings_and_omits_missing_return_date():
    outcome = FlightSearchOutcome(
        flights=[_make_flight("flight_a")], airline_names=set()
    )
    flight_service = _make_flight_service(return_value=outcome)
    airline_review_service = _make_airline_review_service()
    orchestrator = FlightSearchOrchestrator(flight_service, airline_review_service)
    search_request = _make_search_request(
        departure_date=date(2026, 9, 15), return_date=None
    )

    asyncio.run(orchestrator.search_flight(search_request))

    flight_service.search_flight.assert_awaited_once_with(
        origin="TUN",
        destination="YUL",
        departure_date="2026-09-15",
        return_date=None,
    )


def test_search_flight_skips_airline_reviews_when_no_airlines_found():
    outcome = FlightSearchOutcome(
        flights=[_make_flight("flight_a")], airline_names=set()
    )
    flight_service = _make_flight_service(return_value=outcome)
    airline_review_service = _make_airline_review_service()
    orchestrator = FlightSearchOrchestrator(flight_service, airline_review_service)

    response = asyncio.run(orchestrator.search_flight(_make_search_request()))

    assert response.airline_reviews == {}
    airline_review_service.get_airline_summaries.assert_not_awaited()


def test_search_flight_propagates_empty_flight_search_error():
    flight_service = _make_flight_service(
        side_effect=EmptyFlightSearch(
            origin="TUN", destination="YUL", departure_date="2026-08-10"
        )
    )
    airline_review_service = _make_airline_review_service()
    orchestrator = FlightSearchOrchestrator(flight_service, airline_review_service)

    with pytest.raises(EmptyFlightSearch):
        asyncio.run(orchestrator.search_flight(_make_search_request()))

    airline_review_service.get_airline_summaries.assert_not_awaited()
