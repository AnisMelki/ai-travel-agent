from app.core.config import get_settings
from app.tools.apify_flights import FlightSearchService
from app.tools.apify_airlines import AirlineReviewService
from app.tools.flight_selection import FlightSearchOrchestrator

from apify_client import ApifyClient

settings = get_settings()
apify_client = ApifyClient(settings.APIFY_API_TOKEN)

flight_search_service = FlightSearchService(client=apify_client)
airline_review_service = AirlineReviewService(client=apify_client)
