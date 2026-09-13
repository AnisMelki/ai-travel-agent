import uuid
from datetime import date
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.router import flight_router as flight_router_module
from app.schema.chat_schema import ClarificationResponse, FlightSearchRequest
from app.schema.flight_schema import ResponseFlights


class _FakeBootstrapApplication:
    """Stands in for BootstrapApplication so the lifespan never touches real Redis/OpenAI."""

    async def startup(self, app):
        app.state.flight_agent = object()
        app.state.selection_agent = object()
        app.state.redis = object()
        app.state.apify_client = object()

    async def shutdown(self):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        "app.main.BootstrapApplication", lambda: _FakeBootstrapApplication()
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _mock_chat_request_body(message="I want to fly to Paris"):
    return {"message": message}


def _override_orchestrator(fake_orchestrator):
    app.dependency_overrides[flight_router_module.get_orchestrator] = lambda: (
        fake_orchestrator
    )


def test_search_flights_returns_clarification_response(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_flight_request = AsyncMock(
        return_value=ClarificationResponse(
            message="Which city are you leaving from?", field="origin"
        )
    )
    _override_orchestrator(fake_orchestrator)

    response = client.post(
        "/flight/search",
        json=_mock_chat_request_body(),
        headers={"X-Conversation-ID": "conv-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "clarification"
    assert body["message"] == "Which city are you leaving from?"
    fake_orchestrator.handle_flight_request.assert_awaited_once()
    fake_orchestrator.run_flight_selection.assert_not_awaited()


def test_search_flights_returns_flight_result_after_running_selection(client):
    resolved_request = FlightSearchRequest(
        origin="CDG", destination="LHR", departure_date=date(2026, 9, 1)
    )
    result = ResponseFlights(reasoning="Best price and shortest duration.")
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_flight_request = AsyncMock(return_value=resolved_request)
    fake_orchestrator.run_flight_selection = AsyncMock(return_value=result)
    _override_orchestrator(fake_orchestrator)

    response = client.post(
        "/flight/search",
        json=_mock_chat_request_body(),
        headers={"X-Conversation-ID": "conv-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reasoning"] == "Best price and shortest duration."
    fake_orchestrator.run_flight_selection.assert_awaited_once_with(
        resolved_request, "conv-1"
    )


def test_search_flights_passes_message_and_conversation_id_to_orchestrator(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_flight_request = AsyncMock(
        return_value=ClarificationResponse(message="ok")
    )
    _override_orchestrator(fake_orchestrator)

    client.post(
        "/flight/search",
        json=_mock_chat_request_body(message="hello there"),
        headers={"X-Conversation-ID": "conv-42"},
    )

    call_args = fake_orchestrator.handle_flight_request.await_args
    chat_request, conversation_id = call_args.args
    assert chat_request.message == "hello there"
    assert conversation_id == "conv-42"


def test_search_flights_generates_conversation_id_when_header_missing(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_flight_request = AsyncMock(
        return_value=ClarificationResponse(message="ok")
    )
    _override_orchestrator(fake_orchestrator)

    response = client.post("/flight/search", json=_mock_chat_request_body())

    assert response.status_code == 200
    generated_id = response.headers["X-Conversation-ID"]
    assert generated_id
    uuid.UUID(generated_id)  # raises ValueError if this isn't a valid UUID

    _, conversation_id = fake_orchestrator.handle_flight_request.await_args.args
    assert conversation_id == generated_id


def test_search_flights_returns_same_conversation_id_when_header_provided(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_flight_request = AsyncMock(
        return_value=ClarificationResponse(message="ok")
    )
    _override_orchestrator(fake_orchestrator)

    response = client.post(
        "/flight/search",
        json=_mock_chat_request_body(),
        headers={"X-Conversation-ID": "conv-existing"},
    )

    assert response.status_code == 200
    assert response.headers["X-Conversation-ID"] == "conv-existing"
    _, conversation_id = fake_orchestrator.handle_flight_request.await_args.args
    assert conversation_id == "conv-existing"


def test_search_flights_rejects_invalid_request_body(client):
    response = client.post("/flight/search", json={})

    assert response.status_code == 422


def test_search_flights_maps_unexpected_exception_to_500(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_flight_request = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    _override_orchestrator(fake_orchestrator)

    response = client.post(
        "/flight/search",
        json=_mock_chat_request_body(),
        headers={"X-Conversation-ID": "conv-1"},
    )

    assert response.status_code == 500
