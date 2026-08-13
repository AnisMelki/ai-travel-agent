from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.exception.flight_exceptions import TranslatedError


class FlightErrorCode(StrEnum):
    AIRPORT_NOT_FOUND = "airport_not_found"
    AIRPORT_AMBIGUOUS = "airport_ambiguous"
    FLIGHT_REQUEST_VALIDATION_ERROR = "flight_request_validation_error"
    MISSING_REQUIRED_FIELD = "missing_required_field"


class ClarificationOption(BaseModel):
    value: str
    label: str


class ClarificationResponse(BaseModel):
    type: Literal["clarification"] = "clarification"
    message: str
    field: str | None = None
    code: FlightErrorCode | None = None
    missing_fields: list[str] = Field(default_factory=list)
    options: list[ClarificationOption] = Field(default_factory=list)


class ClarificationBuilder:
    _MISSING_FIELD_MESSAGES: dict[str, str] = {
        "origin": ("De quelle ville ou de quel aéroport souhaitez-vous partir ?"),
        "destination": ("Quelle est votre ville ou votre aéroport de destination ?"),
        "departure_date": ("À quelle date souhaitez-vous partir ?"),
        "origin_code": ("Pouvez-vous préciser l’aéroport de départ ou son code IATA ?"),
        "destination_code": (
            "Pouvez-vous préciser l’aéroport d’arrivée ou son code IATA ?"
        ),
    }

    def __init__(self) -> None:
        self._error_builders: dict[
            FlightErrorCode,
            Callable[[TranslatedError], ClarificationResponse],
        ] = {
            FlightErrorCode.AIRPORT_NOT_FOUND: self._build_airport_not_found,
            FlightErrorCode.AIRPORT_AMBIGUOUS: self._build_airport_ambiguity,
            FlightErrorCode.FLIGHT_REQUEST_VALIDATION_ERROR: self._build_validation_error,
        }

    def from_missing_fields(
        self,
        missing_fields: list[str],
    ) -> ClarificationResponse:
        if not missing_fields:
            raise ValueError("missing_fields must contain at least one field.")

        field = missing_fields[0]

        return ClarificationResponse(
            message=self._MISSING_FIELD_MESSAGES.get(
                field,
                f"Pouvez-vous préciser le champ « {field} » ?",
            ),
            field=field,
            code=FlightErrorCode.MISSING_REQUIRED_FIELD,
            missing_fields=missing_fields,
        )

    def from_error(
        self,
        error: TranslatedError,
    ) -> ClarificationResponse:
        if not error.user_correctable:
            raise ValueError(f"Error {error.code!r} is not user-correctable.")

        try:
            code = FlightErrorCode(error.code)
        except ValueError as exc:
            raise ValueError(f"Unsupported clarification code: {error.code!r}") from exc

        builder = self._error_builders.get(code)

        if builder is None:
            raise ValueError(f"No clarification builder registered for {code!r}.")

        return builder(error)

    def _build_airport_not_found(
        self,
        error: TranslatedError,
    ) -> ClarificationResponse:
        return ClarificationResponse(
            message=error.message,
            field=error.field,
            code=FlightErrorCode.AIRPORT_NOT_FOUND,
        )

    def _build_airport_ambiguity(
        self,
        error: TranslatedError,
    ) -> ClarificationResponse:
        airport_codes = (error.details or {}).get("airport_codes", [])
        options = [
            ClarificationOption(value=code, label=code) for code in airport_codes
        ]

        return ClarificationResponse(
            message=error.message,
            field=error.field,
            code=FlightErrorCode.AIRPORT_AMBIGUOUS,
            options=options,
        )

    def _build_validation_error(
        self,
        error: TranslatedError,
    ) -> ClarificationResponse:
        return ClarificationResponse(
            message=error.message,
            field=error.field,
            code=FlightErrorCode.FLIGHT_REQUEST_VALIDATION_ERROR,
        )

    def from_invalid_airport_choice(
        self,
        field_name: str,
        allowed_airport_codes: list[str],
    ) -> ClarificationResponse:
        options = [
            ClarificationOption(value=code, label=code)
            for code in allowed_airport_codes
        ]

        return ClarificationResponse(
            message=(
                "Ce code aéroport n’est pas valide. Merci de choisir l’un des "
                "codes proposés."
            ),
            field=field_name,
            code=FlightErrorCode.AIRPORT_AMBIGUOUS,
            options=options,
        )
