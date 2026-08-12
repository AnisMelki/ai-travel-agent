from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, Field
from datetime import date, datetime
from enum import StrEnum


class ConversationStatus(StrEnum):
    COLLECTING = "collecting"
    VALIDATING = "validating"
    RESOLVING_AIRPORTS = "resolving_airports"
    READY = "ready"
    SEARCHING = "searching"
    COMPLETED = "completed"
    FAILED = "failed"


class PendingClarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal[
        "missing_field",
        "airport_not_found",
        "ambiguous_airport",
    ]

    field_name: Literal[
        "origin",
        "destination",
        "departure_date",
        "return_date",
    ]

    allowed_airport_codes: list[str] = Field(default_factory=list)


class FlightConversationState(BaseModel):
    conversation_id: str
    origin: str | None = None
    destination: str | None = None
    departure_date: date | None = None
    return_date: date | None = None
    origin_code: str | None = None
    destination_code: str | None = None
    status: ConversationStatus = ConversationStatus.COLLECTING
    version: int = 0
    created_at: datetime
    updated_at: datetime
    pending_clarification: PendingClarification | None = None


class FlightRequestPatch(BaseModel):
    origin: str | None = None
    destination: str | None = None
    departure_date: date | None = None
    return_date: date | None = None
    origin_code: str | None = None
    destination_code: str | None = None
    status: ConversationStatus | None = None

    @field_validator("origin_code", "destination_code", mode="before")
    @classmethod
    def normalize_iata_code(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip().upper()

        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("An IATA airport code must contain exactly 3 letters.")

        return normalized
