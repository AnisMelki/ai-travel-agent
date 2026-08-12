from __future__ import annotations
import logging
import re
from typing import Any
from apify_client import ApifyClientAsync
from app.schema.airline_reviews_schema import AirlineReview, AirlineSummary
from app.exception.flight_exceptions import (
    AirlineReviewProviderError,
    AirlineReviewProviderTimeoutError,
    AirlineReviewProviderResponseError,
)

logger = logging.getLogger(__name__)


class AirlineReviewService:
    ACTOR_ID = "knagymate/airlinequality-skytrax-reviews-scraper"

    def __init__(self, client: ApifyClientAsync) -> None:
        self._client = client

    async def get_airline_summaries(
        self,
        airline_names: set[str],
        max_reviews: int = 10,
    ) -> dict[str, AirlineSummary]:
        logger.info(
            "Starting airline review scraping for airlines: %s",
            airline_names,
        )

        summaries: dict[str, AirlineSummary] = {}

        for airline_name in sorted(airline_names):
            logger.info("Scraping reviews for airline: %s", airline_name)

            try:
                reviews = await self._fetch_reviews(
                    airline_name=airline_name,
                    max_reviews=max_reviews,
                )
            except AirlineReviewProviderError:
                logger.exception(
                    "Failed to fetch reviews for airline: %s",
                    airline_name,
                )
                continue

            if not reviews:
                logger.warning(
                    "No reviews found for airline: %s",
                    airline_name,
                )
                continue

            summaries[airline_name] = self._build_summary(reviews)

        return summaries

    async def _fetch_reviews(
        self,
        airline_name: str,
        max_reviews: int,
    ) -> list[AirlineReview]:
        airline_slug = airline_name.strip().lower().replace(" ", "-")

        run_input = {
            "startUrl": (
                f"https://www.airlinequality.com/airline-reviews/{airline_slug}"
            ),
            "maxReviews": max_reviews,
            "cutoffDate": "",
        }

        run = await self._call_actor(run_input=run_input)
        dataset_id = self._default_dataset_id(run)
        items = await self._read_dataset_reviews(dataset_id)

        return [self._review_from_data(item) for item in items]

    @staticmethod
    def _build_summary(
        reviews: list[AirlineReview],
    ) -> AirlineSummary:
        ratings = [review.rating for review in reviews if review.rating is not None]

        average_rating = sum(ratings) / len(ratings) if ratings else 0

        average_verification_rate = (
            sum(1 for review in reviews if review.is_verified is True) / len(reviews)
        ) * 100

        comments = [review.comment for review in reviews if review.comment is not None]

        return AirlineSummary(
            average_rating=average_rating,
            average_verification_rate=average_verification_rate,
            total_comments=comments,
        )

    @staticmethod
    def _review_from_data(item: object) -> AirlineReview:
        if not isinstance(item, dict):
            return AirlineReview()

        return AirlineReview(
            rating=AirlineReviewService._to_rating(item.get("rating")),
            date_published=item.get("date_published"),
            is_verified=item.get("is_verified"),
            country=item.get("country"),
            comment=item.get("comment"),
            title=item.get("title"),
            name=item.get("name"),
        )

    @staticmethod
    def _to_rating(value: object) -> int | None:
        if value is None:
            return None

        if isinstance(value, bool):
            return None

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if isinstance(value, str):
            match = re.search(r"\d+", value)
            return int(match.group()) if match else None

        return None

    @staticmethod
    def _default_dataset_id(run: object) -> str:
        if isinstance(run, dict):
            return run["defaultDatasetId"]

        return run.default_dataset_id

    async def _call_actor(self, run_input: dict) -> list[dict[str, Any]]:
        try:
            return await self._client.actor(self.ACTOR_ID).call(
                run_input=run_input,
                logger=None,
            )

        except TimeoutError as excep:
            raise AirlineReviewProviderTimeoutError(
                "Failed to call Apify actor for airline reviews.",
                details={
                    "Actor ID": self.ACTOR_ID,
                },
            ) from excep
        except Exception as excep:
            raise AirlineReviewProviderError(
                "Failed to call Apify actor for airline reviews.",
                details={"Actor ID": self.ACTOR_ID, "error": type(excep).__name__},
            ) from excep

    async def _read_dataset_reviews(self, dataset_id: str) -> list[dict[str, Any]]:
        try:
            dataset = self._client.dataset(dataset_id)
            return [item async for item in dataset.iterate_items()]
        except TimeoutError as excep:
            raise AirlineReviewProviderTimeoutError(
                "Failed to read dataset from Apify.",
                details={
                    "Dataset ID": dataset_id,
                },
            ) from excep
        except Exception as excep:
            raise AirlineReviewProviderResponseError(
                "Failed to read dataset from Apify.",
                details={"Dataset ID": dataset_id, "error": type(excep).__name__},
            ) from excep
