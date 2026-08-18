import pytest

from app.exception.clarification import (
    ClarificationBuilder,
    ClarificationResponse,
    FlightErrorCode,
)
from app.exception.flight_exceptions import TranslatedError


@pytest.fixture
def builder() -> ClarificationBuilder:
    return ClarificationBuilder()


class TestFromMissingFields:
    def test_builds_response_for_known_field(self, builder: ClarificationBuilder):
        response = builder.from_missing_fields(["origin"])

        assert isinstance(response, ClarificationResponse)
        assert response.type == "clarification"
        assert response.field == "origin"
        assert response.code == FlightErrorCode.MISSING_REQUIRED_FIELD
        assert response.missing_fields == ["origin"]
        assert "partir" in response.message

    def test_builds_generic_message_for_unknown_field(
        self, builder: ClarificationBuilder
    ):
        response = builder.from_missing_fields(["some_unmapped_field"])

        assert response.field == "some_unmapped_field"
        assert "some_unmapped_field" in response.message

    def test_raises_when_missing_fields_is_empty(self, builder: ClarificationBuilder):
        with pytest.raises(ValueError):
            builder.from_missing_fields([])

    def test_only_first_field_is_reflected_in_field_attribute(
        self, builder: ClarificationBuilder
    ):
        response = builder.from_missing_fields(["destination", "departure_date"])

        assert response.field == "destination"
        assert response.missing_fields == ["destination", "departure_date"]


class TestFromError:
    def test_raises_when_error_not_user_correctable(
        self, builder: ClarificationBuilder
    ):
        error = TranslatedError(
            code="flight_provider_timeout",
            category="provider",
            field=None,
            message="Provider timed out.",
            user_correctable=False,
        )

        with pytest.raises(ValueError):
            builder.from_error(error)

    def test_raises_for_unsupported_code(self, builder: ClarificationBuilder):
        error = TranslatedError(
            code="unexpected_error",
            category="technical",
            field=None,
            message="Something went wrong.",
            user_correctable=True,
        )

        with pytest.raises(ValueError):
            builder.from_error(error)

    def test_builds_airport_not_found_response(self, builder: ClarificationBuilder):
        error = TranslatedError(
            code="airport_not_found",
            category="airport_resolution",
            field="origin",
            message="No airport found for Atlantis.",
            details={"location": "atlantis", "field": "origin"},
            user_correctable=True,
        )

        response = builder.from_error(error)

        assert response.code == FlightErrorCode.AIRPORT_NOT_FOUND
        assert response.field == "origin"
        assert response.message == "No airport found for Atlantis."
        assert response.options == []

    def test_builds_airport_ambiguity_response_with_options(
        self, builder: ClarificationBuilder
    ):
        error = TranslatedError(
            code="airport_ambiguous",
            category="airport_resolution",
            field="destination",
            message="Multiple airports found for London.",
            details={
                "location": "london",
                "airport_codes": ["LHR", "LGW", "LCY"],
                "field": "destination",
            },
            user_correctable=True,
        )

        response = builder.from_error(error)

        assert response.code == FlightErrorCode.AIRPORT_AMBIGUOUS
        assert response.field == "destination"
        assert [option.value for option in response.options] == [
            "LHR",
            "LGW",
            "LCY",
        ]
        assert all(option.value == option.label for option in response.options)

    def test_airport_ambiguity_handles_missing_details(
        self, builder: ClarificationBuilder
    ):
        error = TranslatedError(
            code="airport_ambiguous",
            category="airport_resolution",
            field="destination",
            message="Multiple airports found.",
            details=None,
            user_correctable=True,
        )

        response = builder.from_error(error)

        assert response.options == []

    def test_builds_validation_error_response(self, builder: ClarificationBuilder):
        error = TranslatedError(
            code="flight_request_validation_error",
            category="validation",
            field="departure_date",
            message="Departure date must be today or later.",
            details={"errors": [{"field": "departure_date"}]},
            user_correctable=True,
        )

        response = builder.from_error(error)

        assert response.code == FlightErrorCode.FLIGHT_REQUEST_VALIDATION_ERROR
        assert response.field == "departure_date"
        assert response.message == "Departure date must be today or later."
