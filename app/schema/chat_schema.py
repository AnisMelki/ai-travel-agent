from typing_extensions import Annotated

from pydantic import BaseModel, Field, field_validator, ValidationInfo
from datetime import date
from typing import Literal
from dataclasses import dataclass
from app.schema.flight_schema import ResponseFlights, FlightSearchResponse
from app.exception.clarification import ClarificationResponse


class ChatRequest(BaseModel):
    conversation_id: str = Field(
        min_length=1,
        max_length=100,
        description="The unique identifier for the conversation",
    )
    message: str = Field(..., description="The message to be sent to the chatbot")


"""
class FlightResultResponse(BaseModel):
    type: Literal["results"] = Field("results", description="The type of the response")
    message: str = Field(..., description="The message from the chatbot")
    results: ResponseFlights | None = Field(
        None, description="The flight search results, if available"
    )
"""


class ErrorResponse(BaseModel):
    type: Literal["error"] = Field("error", description="The type of the response")
    message: str = Field(..., description="The error message from the chatbot")
    error_code: str = Field(..., description="The error code associated with the error")
    retryable: bool = Field(
        ..., description="Indicates whether the error is retryable or not"
    )


FlightChatResponse = Annotated[
    ClarificationResponse | FlightSearchResponse | ErrorResponse,
    Field(..., description="The type of the response"),
]
FlightResultResponse = Annotated[
    ClarificationResponse | ResponseFlights | ErrorResponse,
    Field(..., description="The type of the response"),
]


class FlightSearchRequest(BaseModel):
    origin: str = Field(..., description="The origin airport code")
    destination: str = Field(..., description="The destination airport code")
    departure_date: date = Field(
        ..., description="The outbound date in YYYY-MM-DD format"
    )
    return_date: date | None = Field(
        None, description="The optional return date in YYYY-MM-DD format"
    )

    @field_validator("destination")
    @classmethod
    def validate_destination(
        cls,
        value: str,
        info: ValidationInfo,
    ) -> str:
        origin = info.data.get("origin")

        if origin is not None and value == origin:
            raise ValueError("Origin and destination cannot be the same.")

        return value

    @field_validator("departure_date")
    @classmethod
    def validate_date(cls, value: date) -> date:
        if value is not None and value < date.today():
            raise ValueError("Departure date cannot be in the past")
        return value

    @field_validator("return_date")
    @classmethod
    def validate_return_date(
        cls,
        value: date | None,
        info: ValidationInfo,
    ) -> date | None:
        departure_date = info.data.get("departure_date")

        if value is not None and departure_date is not None and value < departure_date:
            raise ValueError("Return date cannot be before departure date.")

        return value


@dataclass(frozen=True)
class ResolvedRequest:
    origin_code: str
    destination_code: str
    departure_date: str
    return_date: str | None
