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


def _mock_chat_request_body(conversation_id="conv-1", message="I want to fly to Paris"):
    return {"conversation_id": conversation_id, "message": message}


def test_search_flights_returns_clarification_response(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_flight_request = AsyncMock(
        return_value=(
            ClarificationResponse(
                message="Which city are you leaving from?", field="origin"
            ),
            "conv-1",
        )
    )
    app.dependency_overrides[flight_router_module.get_orchestrator] = (
        lambda: fake_orchestrator
    )

    response = client.post("/flight/search", json=_mock_chat_request_body())

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
    fake_orchestrator.handle_flight_request = AsyncMock(
        return_value=(resolved_request, "conv-1")
    )
    fake_orchestrator.run_flight_selection = AsyncMock(return_value=result)
    app.dependency_overrides[flight_router_module.get_orchestrator] = (
        lambda: fake_orchestrator
    )

    response = client.post("/flight/search", json=_mock_chat_request_body())

    assert response.status_code == 200
    body = response.json()
    assert body["reasoning"] == "Best price and shortest duration."
    fake_orchestrator.run_flight_selection.assert_awaited_once_with(
        resolved_request, "conv-1"
    )


def test_search_flights_passes_request_body_to_orchestrator(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_flight_request = AsyncMock(
        return_value=(ClarificationResponse(message="ok"), "conv-42")
    )
    app.dependency_overrides[flight_router_module.get_orchestrator] = (
        lambda: fake_orchestrator
    )

    client.post(
        "/flight/search",
        json=_mock_chat_request_body(conversation_id="conv-42", message="hello there"),
    )

    chat_request = fake_orchestrator.handle_flight_request.await_args.args[0]
    assert chat_request.conversation_id == "conv-42"
    assert chat_request.message == "hello there"


def test_search_flights_rejects_invalid_request_body(client):
    response = client.post(
        "/flight/search", json={"conversation_id": "", "message": "hi"}
    )

    assert response.status_code == 422


def test_search_flights_maps_unexpected_exception_to_500(client):
    fake_orchestrator = AsyncMock()
    fake_orchestrator.handle_flight_request = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    app.dependency_overrides[flight_router_module.get_orchestrator] = (
        lambda: fake_orchestrator
    )

    response = client.post("/flight/search", json=_mock_chat_request_body())

    assert response.status_code == 500
