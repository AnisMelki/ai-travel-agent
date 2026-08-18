import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exception.flight_exceptions import AirportNotFoundError, AmbiguityAirportError
from app.service.conversation_service.airport_resolve_service import (
    AirportResolutionService,
)


def _make_repository(*, find_by_city_return=None, search_return=None) -> MagicMock:
    repository = MagicMock()
    repository.find_by_city = AsyncMock(return_value=find_by_city_return or [])
    repository.search = AsyncMock(return_value=search_return or [])
    return repository


def test_search_city_returns_code_from_find_by_city_when_unique_match():
    repository = _make_repository(find_by_city_return=["CDG"])
    service = AirportResolutionService(repository)

    result = asyncio.run(service.search_city("Paris"))

    assert result == "CDG"
    repository.search.assert_not_awaited()


def test_search_city_normalizes_city_before_querying_find_by_city():
    repository = _make_repository(find_by_city_return=["CDG"])
    service = AirportResolutionService(repository)

    asyncio.run(service.search_city("  Paris  "))

    repository.find_by_city.assert_awaited_once_with("paris")


def test_search_city_falls_back_to_search_when_find_by_city_returns_nothing():
    repository = _make_repository(find_by_city_return=[], search_return=["ORY"])
    service = AirportResolutionService(repository)

    result = asyncio.run(service.search_city("orly"))

    assert result == "ORY"
    repository.search.assert_awaited_once_with("orly")


def test_search_city_raises_airport_not_found_when_no_matches_anywhere():
    repository = _make_repository(find_by_city_return=[], search_return=[])
    service = AirportResolutionService(repository)

    with pytest.raises(AirportNotFoundError) as exc_info:
        asyncio.run(service.search_city("Atlantis", field="origin"))

    assert exc_info.value.location == "Atlantis"
    assert exc_info.value.field == "origin"


def test_search_city_defaults_field_to_none_when_not_provided():
    repository = _make_repository(find_by_city_return=[], search_return=[])
    service = AirportResolutionService(repository)

    with pytest.raises(AirportNotFoundError) as exc_info:
        asyncio.run(service.search_city("Atlantis"))

    assert exc_info.value.field is None


def test_search_city_raises_ambiguity_error_when_multiple_matches():
    repository = _make_repository(find_by_city_return=["LGW", "LHR", "LCY"])
    service = AirportResolutionService(repository)

    with pytest.raises(AmbiguityAirportError) as exc_info:
        asyncio.run(service.search_city("London", field="destination"))

    assert exc_info.value.location == "London"
    assert exc_info.value.airport_codes == ["LCY", "LGW", "LHR"]
    assert exc_info.value.field == "destination"
    repository.search.assert_not_awaited()


def test_search_city_deduplicates_and_sorts_codes_before_deciding_ambiguity():
    repository = _make_repository(find_by_city_return=["LHR", "CDG", "LHR"])
    service = AirportResolutionService(repository)

    with pytest.raises(AmbiguityAirportError) as exc_info:
        asyncio.run(service.search_city("somewhere"))

    assert exc_info.value.airport_codes == ["CDG", "LHR"]


def test_search_city_returns_single_code_after_deduplication():
    repository = _make_repository(find_by_city_return=["YUL", "YUL"])
    service = AirportResolutionService(repository)

    result = asyncio.run(service.search_city("montreal"))

    assert result == "YUL"
