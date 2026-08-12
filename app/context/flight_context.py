from dataclasses import dataclass
from app.schema.flight_schema import FlightSearchResponse


@dataclass
class FlightAgentContext:
    flight_search_response: FlightSearchResponse | None = None
