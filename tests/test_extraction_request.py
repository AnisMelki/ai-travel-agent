import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.exception.flight_exceptions import (
    AirportNotFoundError,
    FlightExtractionOutputError,
)
from app.schema.chat_schema import ChatRequest
from app.schema.state_conversation import (
    ConversationMessage,
    FlightAgentResponse,
    FlightConversationState,
    FlightRequestPatch,
)
from app.service.conversation_service.extraction_request import (
    FlightExtractionContext,
    FlightExtractionContextFactory,
    FlightRequestExtractionService,
)


def _make_state(**overrides) -> FlightConversationState:
    defaults = {
        "conversation_id": "conv-1",
        "created_at": datetime(2020, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2020, 1, 1, tzinfo=UTC),
    }
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
        history=[ConversationMessage(role="user", message="hello")],
    )

    context = FlightExtractionContextFactory().build(state)

    assert context == FlightExtractionContext(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
        return_date=date(2026, 9, 10),
        origin_code="CDG",
        destination_code="LHR",
        history=[ConversationMessage(role="user", message="hello")],
        current_date=datetime.now(UTC).date(),
    )


# ---------------------------------------------------------------------------
# FlightRequestExtractionService.extract_flight_request
# ---------------------------------------------------------------------------

_RUNNER = "app.service.conversation_service.extraction_request.run_agent_with_retry"


class _FakeMetrics:
    def model_dump(self, **kwargs):
        return {}


def _make_run(final_output):
    """Mimics AgentRunResult(result=RunResult, metrics=LLMCallMetrics)."""
    return SimpleNamespace(
        result=SimpleNamespace(final_output=final_output), metrics=_FakeMetrics()
    )


def _make_agent_response(**patch_fields):
    return FlightAgentResponse(
        type="extraction", patch=FlightRequestPatch(**patch_fields)
    )


def test_extract_flight_request_returns_final_output_on_success():
    expected = _make_agent_response(origin="paris")
    service = FlightRequestExtractionService(agent=object())

    with patch(_RUNNER, new=AsyncMock(return_value=_make_run(expected))):
        result = asyncio.run(
            service.extract_flight_request(_make_chat_request(), _make_state())
        )

    assert result is expected


def test_extract_flight_request_calls_runner_with_agent_message_and_context():
    fake_agent = object()
    service = FlightRequestExtractionService(agent=fake_agent)
    chat_request = _make_chat_request(message="Fly me to Tunis")
    state = _make_state(origin="paris", origin_code="CDG")

    with patch(
        _RUNNER,
        new=AsyncMock(return_value=_make_run(_make_agent_response(origin="tunis"))),
    ) as mock_run:
        asyncio.run(service.extract_flight_request(chat_request, state))

    mock_run.assert_awaited_once()
    call_args = mock_run.call_args
    assert call_args.args == (fake_agent, "Fly me to Tunis")
    assert call_args.kwargs["context"] == FlightExtractionContextFactory().build(state)
    assert call_args.kwargs["conversation_id"] == state.conversation_id


def test_extract_flight_request_raises_output_error_when_final_output_is_none():
    service = FlightRequestExtractionService(agent=object())

    with (
        patch(_RUNNER, new=AsyncMock(return_value=_make_run(None))),
        pytest.raises(FlightExtractionOutputError) as exc_info,
    ):
        asyncio.run(service.extract_flight_request(_make_chat_request(), _make_state()))

    assert exc_info.value.message == "No flight request could be extracted."


def test_extract_flight_request_raises_output_error_when_patch_and_reply_are_empty():
    service = FlightRequestExtractionService(agent=object())
    empty = FlightAgentResponse(type="conversation", patch=FlightRequestPatch())

    with (
        patch(_RUNNER, new=AsyncMock(return_value=_make_run(empty))),
        pytest.raises(FlightExtractionOutputError),
    ):
        asyncio.run(service.extract_flight_request(_make_chat_request(), _make_state()))


def test_extract_flight_request_accepts_a_reply_only_response():
    service = FlightRequestExtractionService(agent=object())
    conversational = FlightAgentResponse(
        type="conversation", patch=FlightRequestPatch(), reply="Bonjour !"
    )

    with patch(_RUNNER, new=AsyncMock(return_value=_make_run(conversational))):
        result = asyncio.run(
            service.extract_flight_request(_make_chat_request(), _make_state())
        )

    assert result.reply == "Bonjour !"


def test_extract_flight_request_reraises_user_correctable_error_from_runner():
    service = FlightRequestExtractionService(agent=object())

    with (
        patch(
            _RUNNER,
            new=AsyncMock(side_effect=AirportNotFoundError("Atlantis", field="origin")),
        ),
        pytest.raises(AirportNotFoundError) as exc_info,
    ):
        asyncio.run(service.extract_flight_request(_make_chat_request(), _make_state()))

    assert exc_info.value.location == "Atlantis"


def test_extract_flight_request_reraises_unexpected_exception_from_runner():
    service = FlightRequestExtractionService(agent=object())

    with (
        patch(_RUNNER, new=AsyncMock(side_effect=RuntimeError("agent run failed"))),
        pytest.raises(RuntimeError, match="agent run failed"),
    ):
        asyncio.run(service.extract_flight_request(_make_chat_request(), _make_state()))
