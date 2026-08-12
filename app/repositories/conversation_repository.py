from typing import Protocol

from app.schema.state_conversation import FlightConversationState


class ConversationRepository(Protocol):
    """Persistence contract for flight conversation state."""

    async def get(
        self,
        conversation_id: str,
    ) -> FlightConversationState | None: ...

    async def save(
        self,
        state: FlightConversationState,
    ) -> None: ...

    async def delete(
        self,
        conversation_id: str,
    ) -> None: ...
