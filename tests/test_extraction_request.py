import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.exception.flight_exceptions import (
    AirportNotFoundError,
    FlightExtractionOutputError,
)
from app.schema.chat_schema import ChatRequest
from app.schema.state_conversation import FlightConversationState, FlightRequestPatch
from app.service.conversation_service.extraction_request import (
    FlightExtractionContext,
    FlightExtractionContextFactory,
    FlightRequestExtractionService,
)


def _make_state(**overrides) -> FlightConversationState:
    defaults = dict(
        conversation_id="conv-1",
        created_at=datetime(2020, 1, 1),
        updated_at=datetime(2020, 1, 1),
    )
    defaults.update(overrides)
    return FlightConversationState(**defaults)


def _make_chat_request(message="I want to fly to Paris") -> ChatRequest:
    return ChatRequest(conversation_id="conv-1", message=message)


# ---------------------------------------------------------------------------
# FlightExtractionContextFactory
# ---------------------------------------------------------------------------


def test_build_maps_all_state_fields_to_context():
    state = _make_state(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
        return_date=date(2026, 9, 10),
        origin_code="CDG",
        destination_code="LHR",
    )

    context = FlightExtractionContextFactory().build(state)

    assert context == FlightExtractionContext(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
        return_date=date(2026, 9, 10),
        origin_code="CDG",
        destination_code="LHR",
    )


# ---------------------------------------------------------------------------
# FlightRequestExtractionService.extract_flight_request
# ---------------------------------------------------------------------------


def test_extract_flight_request_returns_final_output_on_success():
    expected_patch = FlightRequestPatch(origin="paris")
    service = FlightRequestExtractionService(agent=object())

    with patch(
        "app.service.conversation_service.extraction_request.Runner.run",
        new=AsyncMock(return_value=SimpleNamespace(final_output=expected_patch)),
    ):
        result = asyncio.run(
            service.extract_flight_request(_make_chat_request(), _make_state())
        )

    assert result is expected_patch


def test_extract_flight_request_calls_runner_with_agent_message_and_context():
    fake_agent = object()
    service = FlightRequestExtractionService(agent=fake_agent)
    chat_request = _make_chat_request(message="Fly me to Tunis")
    state = _make_state(origin="paris", origin_code="CDG")

    with patch(
        "app.service.conversation_service.extraction_request.Runner.run",
        new=AsyncMock(return_value=SimpleNamespace(final_output=FlightRequestPatch())),
    ) as mock_run:
        asyncio.run(service.extract_flight_request(chat_request, state))

    mock_run.assert_awaited_once()
    call_args = mock_run.call_args
    assert call_args.args == (fake_agent, "Fly me to Tunis")
    assert call_args.kwargs["context"] == FlightExtractionContextFactory().build(state)


def test_extract_flight_request_raises_output_error_when_final_output_is_none():
    service = FlightRequestExtractionService(agent=object())

    with patch(
        "app.service.conversation_service.extraction_request.Runner.run",
        new=AsyncMock(return_value=SimpleNamespace(final_output=None)),
    ):
        with pytest.raises(FlightExtractionOutputError) as exc_info:
            asyncio.run(
                service.extract_flight_request(_make_chat_request(), _make_state())
            )

    assert exc_info.value.message == "No flight request could be extracted."


def test_extract_flight_request_reraises_user_correctable_error_from_runner():
    service = FlightRequestExtractionService(agent=object())

    with patch(
        "app.service.conversation_service.extraction_request.Runner.run",
        new=AsyncMock(side_effect=AirportNotFoundError("Atlantis", field="origin")),
    ):
        with pytest.raises(AirportNotFoundError) as exc_info:
            asyncio.run(
                service.extract_flight_request(_make_chat_request(), _make_state())
            )

    assert exc_info.value.location == "Atlantis"


def test_extract_flight_request_reraises_unexpected_exception_from_runner():
    service = FlightRequestExtractionService(agent=object())

    with patch(
        "app.service.conversation_service.extraction_request.Runner.run",
        new=AsyncMock(side_effect=RuntimeError("agent run failed")),
    ):
        with pytest.raises(RuntimeError, match="agent run failed"):
            asyncio.run(
                service.extract_flight_request(_make_chat_request(), _make_state())
            )
