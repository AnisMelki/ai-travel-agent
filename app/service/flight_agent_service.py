import logging

from agents import Agent
from langfuse import get_client

from app.agent.agent_runner import run_agent_with_retry
from app.context.flight_context import FlightAgentContext
from app.exception.clarification import ClarificationBuilder
from app.exception.flight_exceptions import (
    FlightErrorTranslator,
    UserCorrectableFlightError,
)
from app.hooks.flighs_run_hook import FlightRunHooks
from app.schema.chat_schema import FlightChatResponse, FlightSearchRequest
from app.schema.flight_schema import (
    DecisionFlights,
    FlightSearchResponse,
    ResponseFlights,
)
from app.tools.flight_selection import FlightSearchOrchestrator

logger = logging.getLogger(__name__)


class FlightSelectionService:
    def __init__(
        self,
        flight_search_orchestrator: FlightSearchOrchestrator,
        agent_selection: Agent[FlightAgentContext],
    ) -> None:
        self.flight_search_orchestrator = flight_search_orchestrator
        self.agent_selection = agent_selection

    async def search_flights(
        self, search_request: FlightSearchRequest
    ) -> FlightChatResponse:
        logger.info(
            "Running flight selection service with user input: %s", search_request
        )
        langfuse = get_client()
        with langfuse.start_as_current_observation(
            as_type="tool",
            name="search_flights",
            input=search_request.model_dump_json(),
        ) as span:
            try:
                result = await self.flight_search_orchestrator.search_flight(
                    search_request
                )
                span.update(
                    output=(
                        result.model_dump_json()
                        if hasattr(result, "model_dump_json")
                        else str(result)
                    )
                )
                return result
            except UserCorrectableFlightError as e:
                logger.error("User correctable flight error: %s", str(e))
                translated_error = FlightErrorTranslator()
                user_correctable_error = translated_error.translate(e)
                clarification = ClarificationBuilder().from_error(
                    user_correctable_error
                )
                span.update(output=clarification.model_dump_json())
                return clarification

    async def run_agent_selection(
        self,
        flight_search_response: FlightSearchResponse,
        conversation_id: str,
    ) -> DecisionFlights:
        logger.info(
            "Running flight agent selection with %d flight results",
            len(flight_search_response.results),
        )
        langfuse = get_client()
        with langfuse.start_as_current_observation(
            as_type="chain",
            name="run_agent_selection",
            input=flight_search_response.model_dump_json(),
        ) as span:
            try:
                run = await run_agent_with_retry(
                    self.agent_selection,
                    flight_search_response.model_dump_json(),
                    hooks=FlightRunHooks(),
                    context=FlightAgentContext(
                        flight_search_response=flight_search_response,
                    ),
                    conversation_id=conversation_id,
                )

                span.update(
                    output=(
                        run.result.model_dump_json()
                        if hasattr(run.result, "model_dump_json")
                        else str(run.result)
                    )
                )
                return run.result.final_output
            except Exception:
                logger.exception("Unexpected error during flight agent selection")
                raise

    @staticmethod
    def build_decision_flights_response(
        decision_flights: DecisionFlights, flight_search_response: FlightSearchResponse
    ) -> ResponseFlights:
        if decision_flights is None or flight_search_response is None:
            raise ValueError(
                "decision_flights and flight_search_response must not be None"
            )

        selected_indexes = decision_flights.selected_indexes

        results_count = len(flight_search_response.results)
        out_of_range = [
            index for index in selected_indexes if index < 0 or index >= results_count
        ]
        if out_of_range:
            raise ValueError(
                f"selected_indexes {out_of_range} are out of range for "
                f"flight_search_response.results (length {results_count})"
            )

        best_flight = [
            flight_search_response.results[index] for index in selected_indexes
        ]
        return ResponseFlights(
            best_flights_selected=best_flight, reasoning=decision_flights.reasoning
        )
