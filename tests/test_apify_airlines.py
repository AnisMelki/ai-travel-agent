import asyncio
from types import SimpleNamespace

import pytest

from app.exception.flight_exceptions import (
    AirlineReviewProviderError,
    AirlineReviewProviderResponseError,
    AirlineReviewProviderTimeoutError,
)
from app.tools.apify_airlines import AirlineReviewService


def test_review_from_data_converts_unknown_rating_to_none():
    review = AirlineReviewService._review_from_data(
        {
            "rating": "Unknown",
            "date_published": "2026-07-06 00:00:00",
            "is_verified": True,
            "country": "United States",
            "comment": "Good flight",
            "title": "Good experience",
            "name": "A Smith",
        }
    )

    assert review.rating is None
    assert review.title == "Good experience"


def test_get_airline_summaries_returns_summary():
    captured = {}
    dataset_items = [
        {
            "rating": 8,
            "date_published": "2026-07-06 00:00:00",
            "is_verified": True,
            "country": "United States",
            "comment": "Good flight",
            "title": "Good experience",
            "name": "A Smith",
        },
        {
            "rating": 6,
            "date_published": "2026-07-01 00:00:00",
            "is_verified": False,
            "country": "United States",
            "comment": "Average service",
            "title": "Average service",
            "name": "B Jones",
        },
    ]

    class FakeDataset:
        async def iterate_items(self):
            for item in dataset_items:
                yield item

    class FakeActor:
        async def call(self, run_input, logger=None):
            captured["run_input"] = run_input
            return SimpleNamespace(default_dataset_id="dataset-123")

    class FakeClient:
        def actor(self, actor_id):
            captured["actor_id"] = actor_id
            return FakeActor()

        def dataset(self, dataset_id):
            captured["dataset_id"] = dataset_id
            return FakeDataset()

    service = AirlineReviewService(client=FakeClient())
    result = asyncio.run(
        service.get_airline_summaries({"American Airlines"}, max_reviews=2)
    )

    assert "American Airlines" in result
    assert result["American Airlines"].average_rating == 7
    assert result["American Airlines"].average_verification_rate == 50
    assert result["American Airlines"].total_comments == [
        "Good flight",
        "Average service",
    ]
    assert captured == {
        "actor_id": "knagymate/airlinequality-skytrax-reviews-scraper",
        "run_input": {
            "startUrl": "https://www.airlinequality.com/airline-reviews/american-airlines",
            "maxReviews": 2,
            "cutoffDate": "",
        },
        "dataset_id": "dataset-123",
    }


def test_get_airline_summaries_best_effort_skips_failed_airline():
    class FakeDataset:
        async def iterate_items(self):
            for item in [
                {
                    "rating": 9,
                    "is_verified": True,
                    "comment": "Great",
                }
            ]:
                yield item

    class FakeActor:
        async def call(self, run_input, logger=None):
            if "bad-air" in run_input["startUrl"]:
                raise RuntimeError("boom")
            return SimpleNamespace(default_dataset_id="dataset-123")

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

        def dataset(self, dataset_id):
            return FakeDataset()

    service = AirlineReviewService(client=FakeClient())
    result = asyncio.run(
        service.get_airline_summaries({"Good Air", "Bad Air"}, max_reviews=1)
    )

    assert "Good Air" in result
    assert "Bad Air" not in result


# ---------------------------------------------------------------------------
# _to_rating
# ---------------------------------------------------------------------------


def test_to_rating_returns_none_for_none_value():
    assert AirlineReviewService._to_rating(None) is None


def test_to_rating_returns_none_for_bool_value():
    # bool is an int subclass in Python; must be excluded explicitly.
    assert AirlineReviewService._to_rating(True) is None


def test_to_rating_converts_float_to_int():
    assert AirlineReviewService._to_rating(7.9) == 7


def test_to_rating_returns_none_for_unsupported_type():
    assert AirlineReviewService._to_rating(["9"]) is None


# ---------------------------------------------------------------------------
# _review_from_data / _default_dataset_id
# ---------------------------------------------------------------------------


def test_review_from_data_returns_blank_review_for_non_dict_item():
    review = AirlineReviewService._review_from_data("not-a-dict")

    assert review.rating is None
    assert review.comment is None


def test_default_dataset_id_reads_from_dict_shaped_run():
    dataset_id = AirlineReviewService._default_dataset_id(
        {"defaultDatasetId": "dataset-456"}
    )

    assert dataset_id == "dataset-456"


# ---------------------------------------------------------------------------
# _call_actor
# ---------------------------------------------------------------------------


def test_call_actor_raises_provider_error_when_run_is_none():
    class FakeActor:
        async def call(self, run_input, logger=None):
            return None

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

    service = AirlineReviewService(client=FakeClient())

    with pytest.raises(AirlineReviewProviderError):
        asyncio.run(service._call_actor(run_input={}))


def test_call_actor_raises_timeout_error_on_timeout():
    class FakeActor:
        async def call(self, run_input, logger=None):
            raise TimeoutError("timed out")

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

    service = AirlineReviewService(client=FakeClient())

    with pytest.raises(AirlineReviewProviderTimeoutError):
        asyncio.run(service._call_actor(run_input={}))


# ---------------------------------------------------------------------------
# _read_dataset_reviews
# ---------------------------------------------------------------------------


def test_read_dataset_reviews_raises_timeout_error_on_timeout():
    class FakeDataset:
        async def iterate_items(self):
            raise TimeoutError("timed out")
            yield  # pragma: no cover - makes this an async generator

    class FakeClient:
        def dataset(self, dataset_id):
            return FakeDataset()

    service = AirlineReviewService(client=FakeClient())

    with pytest.raises(AirlineReviewProviderTimeoutError):
        asyncio.run(service._read_dataset_reviews("dataset-123"))


def test_read_dataset_reviews_raises_response_error_on_unexpected_exception():
    class FakeDataset:
        async def iterate_items(self):
            raise RuntimeError("boom")
            yield  # pragma: no cover - makes this an async generator

    class FakeClient:
        def dataset(self, dataset_id):
            return FakeDataset()

    service = AirlineReviewService(client=FakeClient())

    with pytest.raises(AirlineReviewProviderResponseError):
        asyncio.run(service._read_dataset_reviews("dataset-123"))


# ---------------------------------------------------------------------------
# get_airline_summaries
# ---------------------------------------------------------------------------


def test_get_airline_summaries_skips_airline_with_no_reviews_found():
    class FakeDataset:
        async def iterate_items(self):
            return
            yield  # pragma: no cover - makes this an async generator

    class FakeActor:
        async def call(self, run_input, logger=None):
            return SimpleNamespace(default_dataset_id="dataset-123")

    class FakeClient:
        def actor(self, actor_id):
            return FakeActor()

        def dataset(self, dataset_id):
            return FakeDataset()

    service = AirlineReviewService(client=FakeClient())
    result = asyncio.run(service.get_airline_summaries({"Empty Air"}, max_reviews=1))

    assert "Empty Air" not in result
