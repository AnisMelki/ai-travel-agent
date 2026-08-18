from app.schema.chat_schema import FlightSearchRequest
from app.schema.flight_schema import FlightSearchResponse

from app.tools.apify_flights import FlightSearchService
from app.tools.apify_airlines import AirlineReviewService
import logging
from app.schema.chat_schema import ResolvedRequest

logger = logging.getLogger(__name__)


class FlightSearchOrchestrator:
    def __init__(
        self,
        flight_service: FlightSearchService,
        airline_review_service: AirlineReviewService,
    ) -> None:
        self.flight_service = flight_service
        self.airline_review_service = airline_review_service

    async def search_flight(
        self,
        search_request: FlightSearchRequest,
    ) -> FlightSearchResponse:
        logger.info("Validation and parsing of flight search request started.")

        resolved_request = ResolvedRequest(
            origin_code=search_request.origin,
            destination_code=search_request.destination,
            departure_date=search_request.departure_date.isoformat(),
            return_date=(
                search_request.return_date.isoformat()
                if search_request.return_date
                else None
            ),
        )

        logger.info("Flight search request validated and resolved.")
        logger.info(
            "Searching flights from %s to %s on %s with return date %s",
            resolved_request.origin_code,
            resolved_request.destination_code,
            resolved_request.departure_date,
            resolved_request.return_date,
        )

        flight_search_outcome = await self.flight_service.search_flight(
            origin=resolved_request.origin_code,
            destination=resolved_request.destination_code,
            departure_date=resolved_request.departure_date,
            return_date=resolved_request.return_date,
        )

        logger.info("Flight search completed.")

        all_flights = flight_search_outcome.flights
        logger.info("Retrieved %d flights.", len(all_flights))
        airline_reviews_summary = {}
        if flight_search_outcome.airline_names:
            logger.info(
                "Fetching airline reviews for airlines: %s",
                flight_search_outcome.airline_names,
            )
            airline_reviews_summary = (
                await self.airline_review_service.get_airline_summaries(
                    airline_names=flight_search_outcome.airline_names, max_reviews=10
                )
            )
            logger.info("Airline reviews fetched successfully.")
        else:
            logger.info(
                "No airlines found in the search results. Skipping review fetch."
            )
        return FlightSearchResponse(
            results=all_flights, airline_reviews=airline_reviews_summary
        )
