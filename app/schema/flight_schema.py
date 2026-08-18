from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator
from datetime import datetime

from app.schema.airline_reviews_schema import AirlineSummary


class Airport(BaseModel):
    name: str = Field(..., description="The name of the airport")
    id: str = Field(..., description="The unique identifier of the airport")
    time: datetime | None = Field(
        None, description="The time of flight departure or arrival in ISO-8601 format"
    )


class Layover(BaseModel):
    name: str = Field(..., description="The name of the layover airport")
    id: str = Field(..., description="The unique identifier of the layover airport")
    duration: int = Field(..., description="The duration of the layover")


class FlightDetails(BaseModel):
    departure_airport: Airport = Field(
        ..., description="The airport where the flight departs"
    )
    arrival_airport: Airport = Field(
        ..., description="The airport where the flight arrives"
    )
    airline: str = Field(..., description="The airline operating the flight")
    flight_number: str = Field(..., description="The flight number of the flight")
    duration: int = Field(..., description="The duration of the segment of the flight")
    travel_class: str | None = Field(
        None, description="The travel class of the flight (e.g., Economy, Business)"
    )
    airplane_type: str | None = Field(
        None, description="The type of airplane used for the flight"
    )


class FlightSearchResult(BaseModel):
    flights: list[FlightDetails] = Field(..., description="The list of flights")
    total_duration: int | None = Field(
        ..., description="The total duration of the flight"
    )
    layovers: list[Layover] | None = Field(
        None, description="The list of layovers for the flight"
    )
    price: int | None = Field(..., description="The price of the flight")
    type: str = Field(
        ..., description="The type of the flight its round trip or one way"
    )
    currency: str | None = Field(
        None, description="The currency of the price of the flight"
    )


@dataclass(frozen=True)
class FlightSearchOutcome:
    flights: list[FlightSearchResult]
    airline_names: set[str]


class FlightSearchResponse(BaseModel):
    results: list[FlightSearchResult] = Field(
        ..., description="The list of flight search results"
    )
    airline_reviews: dict[str, AirlineSummary] = Field(
        ...,
        description="The airline reviews for the airlines found in the search results",
    )


class DecisionFlights(BaseModel):
    selected_indexes: list[int] = Field(
        max_length=2,
        default_factory=list,
        description="indexes of the selected flights from FlightSearchResponse.results. ordered from the best to second best. empty only when no flights were found in the search results.",
    )

    reasoning: str = Field(
        ...,
        description="Explanation of why these flights were selected based on price, duration, layovers, and airline reviews.",
    )

    @field_validator("selected_indexes")
    @classmethod
    def validate_selected_indexes(cls, indexes: list[int]) -> list:
        if len(indexes) != len(set(indexes)):
            raise ValueError("selected_indexes must contain unique values")
        return indexes


class ResponseFlights(BaseModel):
    best_flights_selected: list[FlightSearchResult] = Field(
        description="list of flight search results selected by the agent. ordered from the best to second best. empty only when no flights were found in the search results.",
        default_factory=list,
    )
    reasoning: str = Field(
        ...,
        description="Explanation of why these flights were selected based on price, duration, layovers, and airline reviews.",
    )
