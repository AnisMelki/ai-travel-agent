from collections.abc import Callable
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import SessionLocal
from app.repositories.airport_repository import AirportRepository
from app.service.conversation_service.merger_completeness_state import (
    FlightStateMerger,
    FlightRequestCompletenessChecker,
)
from app.service.conversation_service.extraction_request import (
    FlightRequestExtractionService,
)
from app.service.conversation_service.airport_resolve_service import (
    AirportResolutionService,
)
from app.schema.state_conversation import (
    FlightConversationState,
    ConversationStatus,
    PendingClarification,
)
from app.schema.chat_schema import (
    ChatRequest,
    ClarificationResponse,
    FlightSearchRequest,
)
from app.exception.flight_exceptions import (
    AirportNotFoundError,
    AmbiguityAirportError,
    TranslatedError,
    UserCorrectableFlightError,
    FlightErrorTranslator,
)
from app.exception.clarification import ClarificationBuilder

import logging

logger = logging.getLogger(__name__)


def _default_airport_resolution_service_factory(
    session: AsyncSession,
) -> AirportResolutionService:
    return AirportResolutionService(AirportRepository(session))


class FlightConversationService:
    _CLARIFICATION_REASON_BY_ERROR_CODE: dict[str, str] = {
        AirportNotFoundError.code: "airport_not_found",
        AmbiguityAirportError.code: "ambiguous_airport",
    }

    def __init__(
        self,
        extraction_service: FlightRequestExtractionService,
        state_merger: FlightStateMerger,
        completeness_checker: FlightRequestCompletenessChecker,
        session_factory: Callable[[], AsyncSession] = SessionLocal,
        airport_resolution_service_factory: Callable[
            [AsyncSession], AirportResolutionService
        ] = _default_airport_resolution_service_factory,
    ):
        self.extraction_service = extraction_service
        self.state_merger = state_merger
        self.completeness_checker = completeness_checker
        self._session_factory = session_factory
        self._airport_resolution_service_factory = airport_resolution_service_factory
        self._error_translator = FlightErrorTranslator()
        self._clarification_builder = ClarificationBuilder()

    async def process_chat_request(
        self,
        chat_request: ChatRequest,
        state: FlightConversationState,
    ) -> tuple[
        FlightSearchRequest | ClarificationResponse,
        FlightConversationState,
    ]:
        logger.info(
            "Processing chat request for conversation_id: %s",
            state.conversation_id,
        )

        # 1. The user is answering a previous clarification.
        if state.pending_clarification is not None:
            return await self._handle_pending_clarification(
                chat_request,
                state,
            )

        # 2. Normal extraction flow.
        state = state.model_copy(
            update={
                "status": ConversationStatus.COLLECTING,
            }
        )

        patch = await self.extraction_service.extract_flight_request(
            chat_request,
            state,
        )

        updated_state = self.state_merger.merge(state, patch)

        # 3. Still missing normal request fields.
        if not self.completeness_checker.is_complete(updated_state):
            missing_fields = self.completeness_checker.missing_fields(updated_state)

            updated_state = updated_state.model_copy(
                update={
                    "status": ConversationStatus.COLLECTING,
                    "pending_clarification": PendingClarification(
                        reason="missing_field",
                        field_name=missing_fields[0],
                    ),
                }
            )

            clarification_response = self._clarification_builder.from_missing_fields(
                missing_fields
            )

            return clarification_response, updated_state

        # 4. All normal fields exist. Resolve airports.
        updated_state = updated_state.model_copy(
            update={
                "status": ConversationStatus.RESOLVING_AIRPORTS,
                "pending_clarification": None,
            }
        )

        return await self._resolve_or_clarify_airports(updated_state)

    async def _handle_pending_clarification(
        self,
        chat_request: ChatRequest,
        state: FlightConversationState,
    ) -> tuple[
        FlightSearchRequest | ClarificationResponse,
        FlightConversationState,
    ]:
        pending = state.pending_clarification

        if pending.reason == "ambiguous_airport":
            return await self._handle_ambiguous_airport_clarification(
                chat_request,
                state,
            )

        # Missing fields can continue through the normal extraction flow.
        if pending.reason in {
            "missing_field",
            "airport_not_found",
        }:
            cleared_state = state.model_copy(
                update={
                    "pending_clarification": None,
                    "status": ConversationStatus.COLLECTING,
                }
            )

            return await self.process_chat_request(
                chat_request,
                cleared_state,
            )

        raise ValueError(f"Unsupported clarification reason: {pending.reason}")

    async def _handle_ambiguous_airport_clarification(
        self,
        chat_request: ChatRequest,
        state: FlightConversationState,
    ) -> tuple[
        FlightSearchRequest | ClarificationResponse,
        FlightConversationState,
    ]:
        pending = state.pending_clarification

        selected_code = chat_request.message.strip().upper()

        if selected_code not in pending.allowed_airport_codes:
            clarification_response = (
                self._clarification_builder.from_invalid_airport_choice(
                    field_name=pending.field_name,
                    allowed_airport_codes=pending.allowed_airport_codes,
                )
            )

            # Keep pending clarification unchanged.
            return clarification_response, state

        updates = {
            "pending_clarification": None,
            "status": ConversationStatus.RESOLVING_AIRPORTS,
        }

        if pending.field_name == "origin":
            updates["origin_code"] = selected_code

        elif pending.field_name == "destination":
            updates["destination_code"] = selected_code

        else:
            raise ValueError(
                "ambiguous_airport clarification must target origin or destination"
            )

        updated_state = state.model_copy(update=updates)

        # Resume airport resolution without losing the user's selection.
        return await self._resolve_or_clarify_airports(updated_state)

    async def _resolve_or_clarify_airports(
        self,
        state: FlightConversationState,
    ) -> tuple[
        FlightSearchRequest | ClarificationResponse,
        FlightConversationState,
    ]:
        try:
            flight_search_request, updated_state = await self._resolve_airport_codes(
                state
            )

            updated_state = updated_state.model_copy(
                update={
                    "status": ConversationStatus.READY,
                    "pending_clarification": None,
                }
            )

            return flight_search_request, updated_state

        except UserCorrectableFlightError as exc:
            logger.warning(
                "Airport resolution requires clarification for conversation_id=%s",
                state.conversation_id,
                exc_info=exc,
            )

            translated_error = self._error_translator.translate(exc)

            clarification_response = self._clarification_builder.from_error(
                translated_error
            )

            updated_state = self._build_pending_clarification_from_error(
                state,
                translated_error,
            )

            return clarification_response, updated_state

    def _build_pending_clarification_from_error(
        self,
        state: FlightConversationState,
        translated_error: TranslatedError,
    ) -> FlightConversationState:
        """
        Convert a user-correctable airport resolution error into
        persistent conversation state.
        """

        reason = self._CLARIFICATION_REASON_BY_ERROR_CODE.get(translated_error.code)

        if reason is None or translated_error.field not in ("origin", "destination"):
            raise ValueError(
                "Cannot build a pending airport clarification from error "
                f"code={translated_error.code!r} field={translated_error.field!r}"
            )

        pending = PendingClarification(
            reason=reason,
            field_name=translated_error.field,
            allowed_airport_codes=(translated_error.details or {}).get(
                "airport_codes", []
            ),
        )

        return state.model_copy(
            update={
                "status": ConversationStatus.RESOLVING_AIRPORTS,
                "pending_clarification": pending,
            }
        )

    async def _resolve_airport_codes(
        self,
        state: FlightConversationState,
    ) -> tuple[
        FlightSearchRequest,
        FlightConversationState,
    ]:
        async with self._session_factory() as session:
            airport_resolution_service = self._airport_resolution_service_factory(
                session
            )

            # Important: do not re-resolve a code already chosen by user.
            origin_code = state.origin_code

            if origin_code is None:
                origin_code = await airport_resolution_service.search_city(
                    state.origin, field="origin"
                )

            destination_code = state.destination_code

            if destination_code is None:
                destination_code = await airport_resolution_service.search_city(
                    state.destination, field="destination"
                )

            updated_state = state.model_copy(
                update={
                    "origin_code": origin_code,
                    "destination_code": destination_code,
                }
            )

        flight_search_request = FlightSearchRequest(
            origin=updated_state.origin_code,
            destination=updated_state.destination_code,
            departure_date=updated_state.departure_date,
            return_date=updated_state.return_date,
        )

        return flight_search_request, updated_state
