import json

from apify_client import ApifyClient
from app.core.config import get_settings
from agents import function_tool
from app.schema.flight_schema import (
    FlightDetails,
    FlightSearchResult,
    FlightSearchResponse,
    Layover,
)


@function_tool
def search_flight(
    origin: str, destination: str, departure_date: str, return_date: str
) -> FlightSearchResponse:
    settings = get_settings()
    client = ApifyClient(settings.APIFY_API_TOKEN)
    run_input = {
        "arrival_id": destination,
        "departure_id": origin,
        "exclude_basic": False,
        "fetch_booking_options": False,
        "outbound_date": departure_date,
        "return_date": return_date,
    }

    run = client.actor(
        "johnvc/Google-Flights-Data-Scraper-Flight-and-Price-Search"
    ).call(run_input=run_input)
    items = list(client.dataset(run.default_dataset_id).iterate_items())

    print("RAW ITEMS:")
    print(items)

    best_flights_returned = items[0]["best_flights"] if items else []

    # other_flights_returned = items[0]["other_flights"] if items else []
    print("BEST FLIGHTS RETURNED:")
    print(best_flights_returned)
    print("TYPE:", type(best_flights_returned))
    print("LENGTH:", len(best_flights_returned))
    best_flights = []
    for f in best_flights_returned:
        best_flights.append(
            FlightSearchResult(
                flights=[
                    FlightDetails(
                        departure_airport=flight.get("departure_airport", "Unknown"),
                        arrival_airport=flight.get("arrival_airport", "Unknown"),
                        airline=flight.get("airline", "Unknown"),
                        flight_number=flight.get("flight_number", "Unknown"),
                        duration=flight.get("duration", "Unknown"),
                        departure_time=flight.get("departure_time"),
                        arrival_time=flight.get("arrival_time"),
                    )
                    for flight in f.get("flights", [])
                ],
                layovers=[
                        Layover(
                            duration=layover["duration"],
                            name=layover["name"],
                            id=layover["id"],
                        )
                        for layover in f.get("layovers", [])
    ],
                total_duration=f.get("total_duration"),
                price=f.get("price"),
                type=f.get("type", "Unknown"),
            )
        )
    return FlightSearchResponse(results=best_flights)
