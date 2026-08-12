import logging
from agents import Agent, Runner
from app.exception.flight_exceptions import UserCorrectableFlightError
from app.schema.chat_schema import FlightChatResponse, FlightSearchRequest
from app.schema.flight_schema import (
    DecisionFlights,
    FlightSearchResponse,
    ResponseFlights,
)
from app.hooks.flighs_run_hook import FlightRunHooks
from app.tools.flight_selection import FlightSearchOrchestrator
from app.exception.flight_exceptions import FlightErrorTranslator
from app.exception.clarification import ClarificationBuilder

logger = logging.getLogger(__name__)


class FlightSelectionService:
    def __init__(
        self,
        flight_search_orchestrator: FlightSearchOrchestrator,
        agent_selection: Agent[None],
    ) -> None:
        self.flight_search_orchestrator = flight_search_orchestrator
        self.agent_selection = agent_selection

    async def search_flights(
        self, search_request: FlightSearchRequest
    ) -> FlightChatResponse:
        logger.info(
            "Running flight selection service with user input: %s", search_request
        )
        try:
            return await self.flight_search_orchestrator.search_flight(search_request)
        except UserCorrectableFlightError as e:
            logger.error("User correctable flight error: %s", str(e))
            translated_error = FlightErrorTranslator()
            user_correctable_error = translated_error.translate(e)
            return ClarificationBuilder().from_error(user_correctable_error)

    async def run_agent_selection(
        self, flight_search_response: FlightSearchResponse
    ) -> DecisionFlights:
        logger.info(
            "Running flight agent selection with %d flight results",
            len(flight_search_response.results),
        )
        try:
            result = await Runner.run(
                self.agent_selection,
                flight_search_response.model_dump_json(),
                hooks=FlightRunHooks(),
            )
            return result.final_output
        except Exception as e:
            logger.exception(
                "Unexpected error during flight agent selection: %s", str(e)
            )
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
