from pydantic import BaseModel, Field
from datetime import datetime


class Airport(BaseModel):
    name: str = Field(..., description="The name of the airport")
    id: str = Field(..., description="The unique identifier of the airport")
    time: datetime = Field(
        ..., description="The time of flight departure or arrival in ISO-8601 format"
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


class FlightSearchResponse(BaseModel):
    results: list[FlightSearchResult] = Field(
        ..., description="The list of flight search results"
    )
