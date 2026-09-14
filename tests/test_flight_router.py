import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.exception.flight_exceptions import (
    AirportNotFoundError,
    EmptyFlightSearch,
    FlightProviderError,
    FlightProviderResponseError,
    FlightProviderTimeoutError,
)
from app.main import app
from app.repositories.redis_conversation_repository import ConversationStorageError
from app.router import flight_router as flight_router_module
from app.schema.chat_schema import ClarificationResponse
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


@pytest.fixture
def handled_client(monkeypatch):
    """TestClient that returns the catch-all handler's response instead of re-raising."""
    monkeypatch.setattr(
        "app.main.BootstrapApplication", lambda: _FakeBootstrapApplication()
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
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
    fake_orchestrator.handle_chat_request = AsyncMock(
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
    fake_orchestrator.handle_chat_request.assert_awaited_once()


def test_search_flights_returns_flight_result_response(client):
    result = ResponseFlights(reasoning="Best price and shortest duration.")
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_chat_request = AsyncMock(return_value=result)
    _override_orchestrator(fake_orchestrator)

    response = client.post(
        "/flight/search",
        json=_mock_chat_request_body(),
        headers={"X-Conversation-ID": "conv-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reasoning"] == "Best price and shortest duration."


def test_search_flights_passes_message_and_conversation_id_to_orchestrator(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_chat_request = AsyncMock(
        return_value=ClarificationResponse(message="ok")
    )
    _override_orchestrator(fake_orchestrator)

    client.post(
        "/flight/search",
        json=_mock_chat_request_body(message="hello there"),
        headers={"X-Conversation-ID": "conv-42"},
    )

    call_args = fake_orchestrator.handle_chat_request.await_args
    chat_request, conversation_id = call_args.args
    assert chat_request.message == "hello there"
    assert conversation_id == "conv-42"


def test_search_flights_generates_conversation_id_when_header_missing(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_chat_request = AsyncMock(
        return_value=ClarificationResponse(message="ok")
    )
    _override_orchestrator(fake_orchestrator)

    response = client.post("/flight/search", json=_mock_chat_request_body())

    assert response.status_code == 200
    generated_id = response.headers["X-Conversation-ID"]
    assert generated_id
    uuid.UUID(generated_id)  # raises ValueError if this isn't a valid UUID

    _, conversation_id = fake_orchestrator.handle_chat_request.await_args.args
    assert conversation_id == generated_id


def test_search_flights_returns_same_conversation_id_when_header_provided(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_chat_request = AsyncMock(
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
    _, conversation_id = fake_orchestrator.handle_chat_request.await_args.args
    assert conversation_id == "conv-existing"


def test_search_flights_rejects_invalid_request_body(client):
    response = client.post("/flight/search", json={})

    assert response.status_code == 422


def test_search_flights_maps_unexpected_exception_to_500(handled_client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_chat_request = AsyncMock(
        side_effect=RuntimeError("boom: secret connection string")
    )
    _override_orchestrator(fake_orchestrator)

    response = handled_client.post(
        "/flight/search",
        json=_mock_chat_request_body(),
        headers={"X-Conversation-ID": "conv-1"},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert "secret connection string" not in body["message"]


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (
            EmptyFlightSearch(origin="CDG", destination="LHR"),
            404,
            "empty_flight_search",
        ),
        (AirportNotFoundError("Atlantis"), 400, "airport_not_found"),
        (
            FlightProviderTimeoutError("upstream slow", provider="Apify"),
            504,
            "flight_provider_timeout",
        ),
        (
            FlightProviderResponseError("bad payload", provider="Apify"),
            502,
            "flight_provider_invalid_response",
        ),
        (
            ConversationStorageError("redis down"),
            503,
            "conversation_storage_unavailable",
        ),
    ],
)
def test_search_flights_maps_domain_errors_to_status_codes(
    client, error, expected_status, expected_code
):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_chat_request = AsyncMock(side_effect=error)
    _override_orchestrator(fake_orchestrator)

    response = client.post(
        "/flight/search",
        json=_mock_chat_request_body(),
        headers={"X-Conversation-ID": "conv-1"},
    )

    assert response.status_code == expected_status
    assert response.json()["error_code"] == expected_code


def test_provider_errors_do_not_leak_internals_to_the_client(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_chat_request = AsyncMock(
        side_effect=FlightProviderError(
            "Apify actor johnvc/scraper failed",
            provider="Apify",
            details={"actor_id": "johnvc/secret-actor"},
        )
    )
    _override_orchestrator(fake_orchestrator)

    response = client.post(
        "/flight/search",
        json=_mock_chat_request_body(),
        headers={"X-Conversation-ID": "conv-1"},
    )

    assert response.status_code == 502
    body = response.json()
    assert "johnvc" not in str(body)
    assert body["retryable"] is True
