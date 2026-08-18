import asyncio

import pytest

from app.exception.flight_exceptions import (
    EmptyFlightSearch,
    FlightProviderError,
    FlightProviderResponseError,
    FlightProviderTimeoutError,
)
from app.tools.apify_flights import FlightSearchService


def _make_raw_flight_segment(duration="2 hr 0 min"):
    return {
        "departure_airport": {
            "name": "A",
            "id": "AAA",
            "time": "2026-08-10T08:00:00",
        },
        "arrival_airport": {
            "name": "B",
            "id": "BBB",
            "time": "2026-08-10T10:00:00",
        },
        "airline": "Example Air",
        "flight_number": "EX100",
        "duration": duration,
    }


def _make_raw_best_flight(price="$100", total_duration="2 hr 0 min"):
    return {
        "flights": [_make_raw_flight_segment()],
        "layovers": [],
        "total_duration": total_duration,
        "price": price,
        "type": "One way",
    }


def _make_raw_dataset_item(best_flights=None):
    return {
        "best_flights": best_flights
        if best_flights is not None
        else [_make_raw_best_flight()]
    }


def test_flight_result_from_data_parses_other_flight_shape():
    from app.tools.apify_flights import FlightSearchService

    result = FlightSearchService._flight_result_from_data(
        {
            "flights": [
                {
                    "departure_airport": {
                        "name": "Tunis-Carthage International Airport",
                        "id": "TUN",
                        "time": "2026-08-10T08:00:00",
                    },
                    "arrival_airport": {
                        "name": "Montreal-Pierre Elliott Trudeau International Airport",
                        "id": "YUL",
                        "time": "2026-08-10T15:00:00",
                    },
                    "airline": "Example Air",
                    "flight_number": "EX123",
                    "duration": "7 hr 0 min",
                }
            ],
            "layovers": [],
            "total_duration": "7 hr 0 min",
            "price": "$650",
            "type": "One way",
        }
    )

    assert result is not None
    assert result.price == 650
    assert result.total_duration == 420
    assert result.flights[0].departure_airport.id == "TUN"


def test_default_dataset_id_accepts_apify_run_object_shape():
    from types import SimpleNamespace

    from app.tools.apify_flights import FlightSearchService

    assert (
        FlightSearchService._default_dataset_id(
            SimpleNamespace(default_dataset_id="dataset-123")
        )
        == "dataset-123"
    )


def test_flight_search_response_accepts_airline_summary_contract():
    from app.schema.flight_schema import (
        Airport,
        FlightDetails,
        FlightSearchResponse,
        FlightSearchResult,
    )
    from app.schema.airline_reviews_schema import AirlineSummary

    result = FlightSearchResult(
        flights=[
            FlightDetails(
                departure_airport=Airport(
                    name="A", id="AAA", time="2026-08-10T08:00:00"
                ),
                arrival_airport=Airport(name="B", id="BBB", time="2026-08-10T10:00:00"),
                airline="Example Air",
                flight_number="EX100",
                duration=120,
            )
        ],
        total_duration=120,
        layovers=[],
        price=100,
        type="One way",
    )

    response = FlightSearchResponse(
        results=[result],
        airline_reviews={
            "Example Air": AirlineSummary(
                average_rating=8,
                average_verification_rate=100,
                total_comments=["Good"],
            )
        },
    )

    assert response.airline_reviews["Example Air"].average_rating == 8


# ---------------------------------------------------------------------------
# _call_actor
# ---------------------------------------------------------------------------


def test_call_actor_returns_dataset_id_on_success():
    class FakeActor:
        async def call(self, run_input, logger=None):
            return {"defaultDatasetId": "dataset-1"}

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

    service = FlightSearchService(client=FakeClient())

    dataset_id = asyncio.run(service._call_actor({}))

    assert dataset_id == "dataset-1"


def test_call_actor_raises_provider_error_when_run_is_none():
    class FakeActor:
        async def call(self, run_input, logger=None):
            return None

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

    service = FlightSearchService(client=FakeClient())

    with pytest.raises(FlightProviderError):
        asyncio.run(service._call_actor({}))


def test_call_actor_raises_timeout_error_on_timeout():
    class FakeActor:
        async def call(self, run_input, logger=None):
            raise TimeoutError("timed out")

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

    service = FlightSearchService(client=FakeClient())

    with pytest.raises(FlightProviderTimeoutError):
        asyncio.run(service._call_actor({}))


def test_call_actor_raises_provider_error_on_unexpected_exception():
    class FakeActor:
        async def call(self, run_input, logger=None):
            raise RuntimeError("boom")

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

    service = FlightSearchService(client=FakeClient())

    with pytest.raises(FlightProviderError):
        asyncio.run(service._call_actor({}))


# ---------------------------------------------------------------------------
# _read_dataset
# ---------------------------------------------------------------------------


def test_read_dataset_returns_items_on_success():
    dataset_items = [{"best_flights": []}, {"best_flights": []}]

    class FakeDataset:
        async def iterate_items(self):
            for item in dataset_items:
                yield item

    class FakeClient:
        def dataset(self, dataset_id):
            return FakeDataset()

    service = FlightSearchService(client=FakeClient())

    items = asyncio.run(service._read_dataset("dataset-1"))

    assert items == dataset_items


def test_read_dataset_raises_timeout_error_on_timeout():
    class FakeDataset:
        async def iterate_items(self):
            raise TimeoutError("timed out")
            yield  # pragma: no cover - makes this an async generator

    class FakeClient:
        def dataset(self, dataset_id):
            return FakeDataset()

    service = FlightSearchService(client=FakeClient())

    with pytest.raises(FlightProviderTimeoutError):
        asyncio.run(service._read_dataset("dataset-1"))


def test_read_dataset_raises_provider_error_on_unexpected_exception():
    class FakeDataset:
        async def iterate_items(self):
            raise RuntimeError("boom")
            yield  # pragma: no cover - makes this an async generator

    class FakeClient:
        def dataset(self, dataset_id):
            return FakeDataset()

    service = FlightSearchService(client=FakeClient())

    with pytest.raises(FlightProviderError):
        asyncio.run(service._read_dataset("dataset-1"))


# ---------------------------------------------------------------------------
# _fetch_dataset_items
# ---------------------------------------------------------------------------


def test_fetch_dataset_items_skips_non_dict_raw_items():
    class FakeActor:
        async def call(self, run_input, logger=None):
            return {"defaultDatasetId": "dataset-1"}

    class FakeDataset:
        async def iterate_items(self):
            for item in ["not-a-dict", _make_raw_dataset_item()]:
                yield item

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

        def dataset(self, dataset_id):
            return FakeDataset()

    service = FlightSearchService(client=FakeClient())

    items = asyncio.run(service._fetch_dataset_items({}))

    assert len(items) == 1
    assert items[0] == _make_raw_dataset_item()


# ---------------------------------------------------------------------------
# search_flight
# ---------------------------------------------------------------------------


def _make_search_flight_client(*, captured, dataset_items):
    class FakeActor:
        async def call(self, run_input, logger=None):
            captured["run_input"] = run_input
            return {"defaultDatasetId": "dataset-1"}

    class FakeDataset:
        async def iterate_items(self):
            for item in dataset_items:
                yield item

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

        def dataset(self, dataset_id):
            return FakeDataset()

    return FakeClient()


def test_search_flight_maps_request_fields_into_apify_run_input():
    captured = {}
    client = _make_search_flight_client(
        captured=captured, dataset_items=[_make_raw_dataset_item()]
    )
    service = FlightSearchService(client=client)

    asyncio.run(service.search_flight("CDG", "LHR", "2026-09-01", "2026-09-10"))

    assert captured["run_input"]["departure_id"] == "CDG"
    assert captured["run_input"]["arrival_id"] == "LHR"
    assert captured["run_input"]["outbound_date"] == "2026-09-01"
    assert captured["run_input"]["return_date"] == "2026-09-10"


def test_search_flight_omits_return_date_when_not_provided():
    captured = {}
    client = _make_search_flight_client(
        captured=captured, dataset_items=[_make_raw_dataset_item()]
    )
    service = FlightSearchService(client=client)

    asyncio.run(service.search_flight("CDG", "LHR", "2026-09-01"))

    assert "return_date" not in captured["run_input"]


def test_search_flight_returns_outcome_with_flights_and_airline_names_on_success():
    captured = {}
    client = _make_search_flight_client(
        captured=captured, dataset_items=[_make_raw_dataset_item()]
    )
    service = FlightSearchService(client=client)

    outcome = asyncio.run(service.search_flight("CDG", "LHR", "2026-09-01"))

    assert len(outcome.flights) == 1
    assert outcome.flights[0].price == 100
    assert outcome.airline_names == {"Example Air"}


def test_search_flight_raises_response_error_when_dataset_items_empty():
    captured = {}
    client = _make_search_flight_client(captured=captured, dataset_items=[])
    service = FlightSearchService(client=client)

    with pytest.raises(FlightProviderResponseError):
        asyncio.run(service.search_flight("CDG", "LHR", "2026-09-01"))


def test_search_flight_raises_empty_flight_search_when_no_flights_parsed():
    captured = {}
    client = _make_search_flight_client(
        captured=captured, dataset_items=[{"best_flights": []}]
    )
    service = FlightSearchService(client=client)

    with pytest.raises(EmptyFlightSearch):
        asyncio.run(service.search_flight("CDG", "LHR", "2026-09-01"))


# ---------------------------------------------------------------------------
# _extract_flight_results
# ---------------------------------------------------------------------------


def test_extract_flight_results_skips_items_with_non_list_best_flights():
    service = FlightSearchService(client=None)

    results = service._extract_flight_results(
        [{"best_flights": "not-a-list"}, _make_raw_dataset_item()]
    )

    assert len(results) == 1


def test_extract_flight_results_collects_flights_across_multiple_items():
    service = FlightSearchService(client=None)

    results = service._extract_flight_results(
        [_make_raw_dataset_item(), _make_raw_dataset_item()]
    )

    assert len(results) == 2


# ---------------------------------------------------------------------------
# _default_dataset_id
# ---------------------------------------------------------------------------


def test_default_dataset_id_accepts_dict_shaped_run():
    assert (
        FlightSearchService._default_dataset_id({"defaultDatasetId": "dataset-456"})
        == "dataset-456"
    )


def test_default_dataset_id_raises_when_dataset_id_missing_or_invalid():
    with pytest.raises(FlightProviderResponseError):
        FlightSearchService._default_dataset_id({"defaultDatasetId": ""})


# ---------------------------------------------------------------------------
# _extract_airline_names
# ---------------------------------------------------------------------------


def test_extract_airline_names_dedupes_and_excludes_unknown():
    from app.schema.flight_schema import Airport, FlightDetails, FlightSearchResult

    def _flight(airline):
        return FlightDetails(
            departure_airport=Airport(name="A", id="AAA"),
            arrival_airport=Airport(name="B", id="BBB"),
            airline=airline,
            flight_number="EX1",
            duration=60,
        )

    results = [
        FlightSearchResult(
            flights=[_flight("Example Air"), _flight("  Example Air  ")],
            total_duration=60,
            layovers=[],
            price=100,
            type="One way",
        ),
        FlightSearchResult(
            flights=[_flight("Unknown")],
            total_duration=60,
            layovers=[],
            price=100,
            type="One way",
        ),
    ]

    names = FlightSearchService._extract_airline_names(results)

    assert names == {"Example Air"}


# ---------------------------------------------------------------------------
# _flight_result_from_data invalid duration/price
# ---------------------------------------------------------------------------


def test_flight_result_from_data_returns_none_when_total_duration_invalid():
    result = FlightSearchService._flight_result_from_data(
        _make_raw_best_flight(total_duration=None)
    )

    assert result is None


def test_flight_result_from_data_returns_none_when_price_invalid():
    result = FlightSearchService._flight_result_from_data(
        _make_raw_best_flight(price=None)
    )

    assert result is None


# ---------------------------------------------------------------------------
# _to_price / _to_duration_minutes (optional, type-coercion branches)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        (True, None),
        (42, 42),
        (19.9, 19),
        (["100"], None),
    ],
)
def test_to_price_handles_none_bool_int_float_and_unsupported_type(value, expected):
    assert FlightSearchService._to_price(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        (True, None),
        (90, 90),
        (45.9, 45),
        ("45", 45),
        (["90"], None),
    ],
)
def test_to_duration_minutes_handles_none_bool_int_float_and_digits_only_string(
    value, expected
):
    assert FlightSearchService._to_duration_minutes(value) == expected


# ---------------------------------------------------------------------------
# _to_datetime (optional)
# ---------------------------------------------------------------------------


def test_to_datetime_falls_back_to_manual_format_when_iso_parse_fails():
    from datetime import UTC, datetime

    result = FlightSearchService._to_datetime("08/10/2026 08:00 AM")

    assert result == datetime(2026, 8, 10, 8, 0, tzinfo=UTC)


def test_to_datetime_returns_none_when_unparseable():
    assert FlightSearchService._to_datetime("not-a-date") is None


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        (True, None),  # not a str -> falls through to the non-str branch
        ("", None),
    ],
)
def test_to_datetime_handles_none_passthrough_and_non_str_and_empty(value, expected):
    assert FlightSearchService._to_datetime(value) == expected


def test_to_datetime_returns_same_instance_for_datetime_value():
    from datetime import datetime

    value = datetime(2026, 8, 10, 8, 0)

    assert FlightSearchService._to_datetime(value) is value


# ---------------------------------------------------------------------------
# _layover_from_data (optional)
# ---------------------------------------------------------------------------


def test_layover_from_data_parses_valid_layover():
    from app.tools.apify_flights import FlightSearchService as Service

    layover = Service._layover_from_data(
        {"name": "Doha", "id": "DOH", "duration": "1 hr 30 min"}
    )

    assert layover is not None
    assert layover.duration == 90
    assert layover.id == "DOH"


def test_layover_from_data_returns_none_when_duration_invalid():
    layover = FlightSearchService._layover_from_data(
        {"name": "Doha", "id": "DOH", "duration": None}
    )

    assert layover is None
