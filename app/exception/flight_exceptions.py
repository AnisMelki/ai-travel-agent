from dataclasses import dataclass
from typing import Any
from pydantic import ValidationError
from app.schema.state_conversation import FlightFieldName


@dataclass(frozen=True, slots=True)
class TranslatedError:
    code: str
    category: str
    field: FlightFieldName | None
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False
    user_correctable: bool = False


class FlightError(Exception):
    """Base class for all flight-domain exceptions."""

    code = "flight_error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class UserCorrectableFlightError(FlightError):
    """An error that can be corrected through user clarification."""


class FlightExtractionOutputError(UserCorrectableFlightError):
    """Raised when the flight extraction output is invalid."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)


class ProviderError(FlightError):
    """Base class for external provider failures."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        provider_details = {
            "provider": provider,
            **(details or {}),
        }

        super().__init__(
            message,
            details=provider_details,
        )

        self.provider = provider


class FlightProviderError(ProviderError):
    """Base class for flight-search provider failures."""


class FlightProviderTimeoutError(FlightProviderError):
    code = "flight_provider_timeout"


class FlightProviderResponseError(FlightProviderError):
    code = "flight_provider_invalid_response"


class AirlineReviewProviderError(ProviderError):
    """Base class for airline-review provider failures."""


class AirlineReviewProviderTimeoutError(AirlineReviewProviderError):
    code = "airline_review_provider_timeout"


class AirlineReviewProviderResponseError(AirlineReviewProviderError):
    code = "airline_review_provider_invalid_response"


class EmptyFlightSearch(UserCorrectableFlightError):
    """Raised when no flights match the search criteria."""

    code = "empty_flight_search"

    def __init__(
        self,
        *,
        origin: str | None = None,
        destination: str | None = None,
        departure_date: str | None = None,
    ) -> None:
        super().__init__(
            "No flights were found for the requested itinerary.",
            details={
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
            },
        )


class AirportNotFoundError(UserCorrectableFlightError):
    code = "airport_not_found"

    def __init__(
        self,
        location: str,
        *,
        field: FlightFieldName | None = None,
    ) -> None:
        self.location = location
        self.field = field

        super().__init__(
            f"No airport was found for location: {location}",
            details={
                "location": location,
                "field": field,
            },
        )


class AmbiguityAirportError(UserCorrectableFlightError):
    code = "airport_ambiguous"

    def __init__(
        self,
        location: str,
        airport_codes: list[str],
        *,
        field: FlightFieldName | None = None,
    ) -> None:
        self.location = location
        self.airport_codes = airport_codes
        self.field = field

        super().__init__(
            f"Multiple airports were found for location: {location}",
            details={
                "location": location,
                "airport_codes": airport_codes,
                "field": field,
            },
        )


class FlightRequestValidationError(UserCorrectableFlightError):
    """Raised when flight-request business validation fails."""

    code = "flight_request_validation_error"

    def __init__(
        self,
        errors: list[dict[str, Any]],
    ) -> None:
        self.errors = errors

        super().__init__(
            "Flight request contains invalid data.",
            details={
                "errors": errors,
            },
        )


class FlightErrorTranslator:
    def translate(self, error: Exception) -> TranslatedError:
        match error:
            case AirportNotFoundError():
                return TranslatedError(
                    code=error.code,
                    category="airport_resolution",
                    field=error.field,
                    message=(
                        f"Je n’ai trouvé aucun aéroport correspondant à "
                        f"« {error.location} ». Pouvez-vous préciser la ville "
                        f"ou le code IATA ?"
                    ),
                    details=error.details,
                    user_correctable=True,
                )

            case AmbiguityAirportError():
                codes = ", ".join(error.airport_codes)

                return TranslatedError(
                    code=error.code,
                    category="airport_resolution",
                    field=error.field,
                    message=(
                        f"Plusieurs aéroports correspondent à "
                        f"« {error.location} » : {codes}. "
                        f"Lequel souhaitez-vous utiliser ?"
                    ),
                    details=error.details,
                    user_correctable=True,
                )

            case EmptyFlightSearch():
                return TranslatedError(
                    code=error.code,
                    category="flight_search",
                    field=None,
                    message=(
                        "Je n’ai trouvé aucun vol pour ces critères. "
                        "Souhaitez-vous modifier la date ou les aéroports ?"
                    ),
                    details=error.details,
                    user_correctable=True,
                )

            case FlightRequestValidationError():
                return self._translate_validation_error(error)

            case FlightProviderTimeoutError():
                return TranslatedError(
                    code=error.code,
                    category="provider",
                    field=None,
                    message=(
                        "Le service de recherche de vols met trop de temps "
                        "à répondre. Veuillez réessayer."
                    ),
                    details=error.details,
                    retryable=True,
                )

            case AirlineReviewProviderTimeoutError():
                return TranslatedError(
                    code=error.code,
                    category="provider",
                    field=None,
                    message=(
                        "Les avis sur les compagnies aériennes sont "
                        "temporairement indisponibles."
                    ),
                    details=error.details,
                    retryable=True,
                )

            case ProviderError():
                return TranslatedError(
                    code=getattr(error, "code", "provider_error"),
                    category="provider",
                    field=None,
                    message=("Un service externe est temporairement indisponible."),
                    details=error.details,
                    retryable=True,
                )

            case FlightError():
                return TranslatedError(
                    code=getattr(error, "code", "flight_error"),
                    category="business",
                    field=None,
                    message=error.message,
                    details=error.details,
                )
            case FlightExtractionOutputError():
                return TranslatedError(
                    code=error.code,
                    category="extraction",
                    field=None,
                    message=(
                        "Impossible d’extraire les informations de vol à partir de la demande."
                    ),
                    details=error.details,
                    user_correctable=False,
                )

            case _:
                return TranslatedError(
                    code="unexpected_error",
                    category="technical",
                    field=None,
                    message="Une erreur inattendue est survenue.",
                    details=None,
                    retryable=False,
                    user_correctable=False,
                )

    def _translate_validation_error(
        self,
        error: FlightRequestValidationError,
    ) -> TranslatedError:
        first_error = error.errors[0] if error.errors else {}

        field = first_error.get("field")
        error_type = first_error.get("type")
        context = first_error.get("context", {})

        message = self._validation_message(
            field=field,
            error_type=error_type,
            context=context,
        )

        return TranslatedError(
            code=error.code,
            category="validation",
            field=field,
            message=message,
            details=error.details,
            user_correctable=True,
        )

    @staticmethod
    def _validation_message(
        *,
        field: str | None,
        error_type: str | None,
        context: dict[str, Any],
    ) -> str:
        messages = {
            "same_origin_destination": (
                "L’origine et la destination doivent être différentes. "
                "Quelle destination souhaitez-vous utiliser ?"
            ),
            "departure_date_in_past": (
                "La date de départ doit être aujourd’hui ou dans le futur. "
                "Quelle nouvelle date souhaitez-vous utiliser ?"
            ),
            "return_before_departure": (
                "La date de retour doit être postérieure ou égale "
                "à la date de départ. Quelle date de retour souhaitez-vous ?"
            ),
            "missing": (
                f"Le champ « {field} » est requis."
                if field
                else "Une information obligatoire est manquante."
            ),
        }
        if error_type is None:
            return "Invalid Flights Request"
        else:
            return messages.get(
                error_type,
                "Certaines informations de la demande sont invalides. "
                "Pouvez-vous les vérifier ?",
            )


def normalize_validation_errors(
    exc: ValidationError,
) -> list[dict[str, Any]]:
    normalized_errors: list[dict[str, Any]] = []

    for error in exc.errors():
        location = error.get("loc", ())

        normalized_errors.append(
            {
                "field": str(location[-1]) if location else None,
                "type": str(error.get("type", "validation_error")),
                "message": str(error.get("msg", "Invalid value.")),
                "context": error.get("ctx") or {},
            }
        )

    return normalized_errors
