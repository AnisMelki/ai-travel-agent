import re
from datetime import date, datetime
from typing import Any
from apify_client import ApifyClientAsync
from app.schema.flight_schema import (
    Airport,
    FlightDetails,
    FlightSearchResult,
    FlightSearchOutcome,
    Layover,
)
from app.exception.flight_exceptions import (
    FlightProviderError,
    FlightProviderTimeoutError,
    FlightProviderResponseError,
    EmptyFlightSearch,
)
import logging

logger = logging.getLogger(__name__)


class FlightSearchService:
    ACTOR_ID = "johnvc/Google-Flights-Data-Scraper-Flight-and-Price-Search"

    def __init__(self, client: ApifyClientAsync) -> None:
        self._client = client

    async def search_flight(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
    ) -> FlightSearchOutcome:
        run_input = {
            "arrival_id": destination,
            "departure_id": origin,
            "exclude_basic": False,
            "fetch_booking_options": False,
            "outbound_date": departure_date,
        }
        if return_date:
            run_input["return_date"] = return_date

        logger.info(
            "Starting flight search with input:",
            extra={
                "event": "flight_search_started",
                "actor_id": self.ACTOR_ID,
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
                "has_return_date": return_date is not None,
            },
        )
        items = await self._fetch_dataset_items(run_input)
        if not items:
            raise FlightProviderResponseError(
                "Apify flight search returned no dataset items",
                details={"actor_id": self.ACTOR_ID},
            )
        all_flights = self._extract_flight_results(items)
        if not all_flights:
            raise EmptyFlightSearch(
                "Flight search completed but no flights were found",
                details={
                    "origin": origin,
                    "destination": destination,
                    "departure_date": departure_date,
                    "return_date": return_date,
                },
            )
        airline_names = self._extract_airline_names(all_flights)
        logger.info(
            "Flight search completed successfully with %d flights found",
            len(all_flights),
        )
        return FlightSearchOutcome(flights=all_flights, airline_names=airline_names)

    async def _fetch_dataset_items(
        self,
        run_input: dict[str, Any],
    ) -> list[dict[str, Any]]:
        run = await self._call_actor(run_input)

        dataset_id = self._default_dataset_id(run)

        raw_items = await self._read_dataset(dataset_id)

        logger.info(
            "Apify flight dataset returned %d items",
            len(raw_items),
        )

        if raw_items and isinstance(raw_items[0], dict):
            logger.info(
                "First Apify flight item keys: %s",
                sorted(raw_items[0].keys()),
            )

        items: list[dict[str, Any]] = []

        for item in raw_items:
            if not isinstance(item, dict):
                logger.warning(
                    "Skipping non-dict Apify flight item: %s",
                    type(item).__name__,
                )
                continue

            items.append(item)

        return items

    def _extract_flight_results(
        self,
        items: list[dict[str, Any]],
    ) -> list[FlightSearchResult]:
        all_flights: list[FlightSearchResult] = []

        for flight_data in items:
            best_flights_returned = flight_data.get(
                "best_flights",
                [],
            )

            if not isinstance(best_flights_returned, list):
                logger.warning(
                    "Skipping invalid best_flights payload: %s",
                    type(best_flights_returned).__name__,
                )
                continue

            for raw_flight in best_flights_returned:
                flight_result = self._flight_result_from_data(raw_flight)

                if flight_result is not None:
                    all_flights.append(flight_result)

        return all_flights

    @classmethod
    def _flight_result_from_data(
        cls,
        value: object,
    ) -> FlightSearchResult | None:
        if not isinstance(value, dict):
            return None

        raw_flights = value.get("flights", [])

        if not isinstance(raw_flights, list):
            return None

        flights = [
            flight
            for item in raw_flights
            if (flight := cls._flight_from_data(item)) is not None
        ]

        if not flights:
            return None

        raw_layovers = value.get("layovers", [])

        if not isinstance(raw_layovers, list):
            raw_layovers = []

        layovers = [
            layover
            for item in raw_layovers
            if (layover := cls._layover_from_data(item)) is not None
        ]

        total_duration = cls._to_duration_minutes(value.get("total_duration"))
        price = cls._to_price(value.get("price"))

        if total_duration is None:
            logger.warning("Skipping flight result with invalid total duration")
            return None

        if price is None:
            logger.warning("Skipping flight result with invalid price")
            return None

        return FlightSearchResult(
            flights=flights,
            layovers=layovers,
            total_duration=total_duration,
            price=price,
            type=cls._to_str(value.get("type")),
        )

    @classmethod
    def _flight_from_data(
        cls,
        value: object,
    ) -> FlightDetails | None:
        if not isinstance(value, dict):
            return None

        departure_airport = cls._airport_from_data(value.get("departure_airport"))
        arrival_airport = cls._airport_from_data(value.get("arrival_airport"))
        duration = cls._to_duration_minutes(value.get("duration"))

        if departure_airport is None or arrival_airport is None or duration is None:
            return None

        return FlightDetails(
            departure_airport=departure_airport,
            arrival_airport=arrival_airport,
            airline=cls._to_str(value.get("airline")),
            flight_number=cls._to_str(value.get("flight_number")),
            duration=duration,
            travel_class=value.get("travel_class"),
            airplane_type=value.get("airplane"),
        )

    @classmethod
    def _airport_from_data(
        cls,
        value: object,
    ) -> Airport | None:
        if not isinstance(value, dict):
            return None

        return Airport(
            name=cls._to_str(value.get("name")),
            id=cls._to_str(value.get("id")),
            time=cls._to_datetime(value.get("time")),
        )

    @classmethod
    def _layover_from_data(
        cls,
        value: object,
    ) -> Layover | None:
        if not isinstance(value, dict):
            return None

        duration = cls._to_duration_minutes(value.get("duration"))

        if duration is None:
            return None

        return Layover(
            duration=duration,
            name=cls._to_str(value.get("name")),
            id=cls._to_str(value.get("id")),
        )

    @staticmethod
    def _default_dataset_id(run: object) -> str:
        if isinstance(run, dict):
            dataset_id = run.get("defaultDatasetId")
        else:
            dataset_id = getattr(
                run,
                "default_dataset_id",
                None,
            )

        if not isinstance(dataset_id, str) or not dataset_id:
            raise FlightProviderResponseError(
                "Apify flight search run did not return a valid dataset ID",
                details={"response_type": type(run).__name__},
            )

        return dataset_id

    @staticmethod
    def _to_price(value: object) -> int | None:
        if value is None or isinstance(value, bool):
            return None

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if isinstance(value, str):
            digits = "".join(character for character in value if character.isdigit())

            return int(digits) if digits else None

        return None

    @staticmethod
    def _to_duration_minutes(
        value: object,
    ) -> int | None:
        if value is None or isinstance(value, bool):
            return None

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if not isinstance(value, str):
            return None

        normalized = value.lower().strip()

        hours = re.search(
            r"(\d+)\s*(?:h|hr|hrs|hour|hours)\b",
            normalized,
        )
        minutes = re.search(
            r"(\d+)\s*(?:m|min|mins|minute|minutes)\b",
            normalized,
        )

        if hours or minutes:
            total = 0

            if hours:
                total += int(hours.group(1)) * 60

            if minutes:
                total += int(minutes.group(1))

            return total

        digits = "".join(character for character in normalized if character.isdigit())

        return int(digits) if digits else None

    @staticmethod
    def _to_str(
        value: object,
        default: str = "Unknown",
    ) -> str:
        return str(value) if value not in (None, "") else default

    @staticmethod
    def _to_datetime(
        value: object,
    ) -> datetime | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            return value

        if not isinstance(value, str):
            return None

        normalized = value.strip()

        if not normalized:
            return None

        try:
            return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            pass

        date_formats = (
            "%Y-%m-%d %I:%M %p",
            "%Y-%m-%d %H:%M",
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %H:%M",
            "%b %d, %Y %I:%M %p",
            "%B %d, %Y %I:%M %p",
        )

        for date_format in date_formats:
            try:
                return datetime.strptime(
                    normalized,
                    date_format,
                )
            except ValueError:
                continue

        return None

    @staticmethod
    def _extract_airline_names(
        flight_results: list[FlightSearchResult],
    ) -> set[str]:
        airline_names: set[str] = set()

        for flight_result in flight_results:
            for flight_segment in flight_result.flights:
                airline_name = flight_segment.airline.strip()

                if airline_name and airline_name != "Unknown":
                    airline_names.add(airline_name)

        return airline_names

    async def _call_actor(self, run_input: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._client.actor(self.ACTOR_ID).call(
                run_input=run_input,
                logger=None,
            )

        except TimeoutError as exc:
            raise FlightProviderTimeoutError(
                "Apify flight search timed out", details={"actor_id": self.ACTOR_ID}
            ) from exc
        except Exception as exc:
            logger.exception(
                "Apify flight search failed with an exception: %s",
                exc_info=exc,
                extra={
                    "actor_id": self.ACTOR_ID,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )
            raise FlightProviderError(
                "Apify flight search failed",
                details={
                    "actor_id": self.ACTOR_ID,
                    "exception_type": type(exc).__name__,
                },
            ) from exc

    async def _read_dataset(self, dataset_id: str) -> list[dict[str, Any]]:
        try:
            return [
                item async for item in self._client.dataset(dataset_id).iterate_items()
            ]
        except TimeoutError as exc:
            raise FlightProviderTimeoutError(
                "Apify dataset read timed out", details={"dataset_id": dataset_id}
            ) from exc
        except Exception as exc:
            raise FlightProviderError(
                "Apify dataset read failed",
                details={
                    "dataset_id": dataset_id,
                    "exception_type": type(exc).__name__,
                },
            ) from exc
