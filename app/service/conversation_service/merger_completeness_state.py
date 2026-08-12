from datetime import datetime
from app.schema.state_conversation import FlightConversationState, FlightRequestPatch


class FlightStateMerger:
    def merge(
        self, current_state: FlightConversationState, patch: FlightRequestPatch
    ) -> FlightConversationState:
        updates = patch.model_dump(exclude_none=True)
        if "origin" in updates:
            updates["origin"] = self._normalize_location(updates["origin"])

        if "destination" in updates:
            updates["destination"] = self._normalize_location(updates["destination"])

        return current_state.model_copy(
            update={
                **updates,
                "origin_code": (
                    None if "origin" in updates else current_state.origin_code
                ),
                "destination_code": (
                    None if "destination" in updates else current_state.destination_code
                ),
                "version": current_state.version + 1,
                "updated_at": datetime.now(),
            }
        )

    @staticmethod
    def _normalize_location(value: str) -> str:
        return value.strip().lower()


class FlightRequestCompletenessChecker:
    REQUIRED_FIELDS: tuple[str, ...] = (
        "origin",
        "destination",
        "departure_date",
    )

    def missing_fields(
        self,
        state: FlightConversationState,
    ) -> list[str]:
        return [
            field_name
            for field_name in self.REQUIRED_FIELDS
            if getattr(state, field_name) is None
        ]

    def is_complete(
        self,
        state: FlightConversationState,
    ) -> bool:
        return not self.missing_fields(state)
