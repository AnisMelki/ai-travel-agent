import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.schema.state_conversation import (
    FlightConversationState,
)

logger = logging.getLogger(__name__)


class ConversationStorageError(Exception):
    """Raised when conversation state storage is unavailable."""


class RedisConversationRepository:
    KEY_PREFIX = "flight:conversation"

    def __init__(
        self,
        redis_client: Redis,
        ttl_seconds: int,
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    def _build_key(self, conversation_id: str) -> str:
        return f"{self.KEY_PREFIX}:{conversation_id}"

    async def get(
        self,
        conversation_id: str,
    ) -> FlightConversationState | None:
        key = self._build_key(conversation_id)

        try:
            raw_state = await self._redis.get(key)
        except RedisError as exc:
            logger.exception(
                "Failed to read conversation state",
                extra={
                    "event": "conversation_state_read_failed",
                    "conversation_id": conversation_id,
                },
            )
            raise ConversationStorageError(
                "Unable to read conversation state."
            ) from exc

        if raw_state is None:
            return None

        try:
            return FlightConversationState.model_validate_json(raw_state)
        except ValueError as exc:
            logger.exception(
                "Invalid conversation state stored in Redis",
                extra={
                    "event": "conversation_state_deserialization_failed",
                    "conversation_id": conversation_id,
                },
            )
            raise ConversationStorageError(
                "Stored conversation state is invalid."
            ) from exc

    async def save(
        self,
        state: FlightConversationState,
    ) -> None:
        key = self._build_key(state.conversation_id)

        try:
            serialized_state = state.model_dump_json()
            await self._redis.set(
                name=key,
                value=serialized_state,
                ex=self._ttl_seconds,
            )
        except (RedisError, ValueError) as exc:
            logger.exception(
                "Failed to save conversation state",
                extra={
                    "event": "conversation_state_save_failed",
                    "conversation_id": state.conversation_id,
                    "version": state.version,
                },
            )
            raise ConversationStorageError(
                "Unable to save conversation state."
            ) from exc

    async def delete(
        self,
        conversation_id: str,
    ) -> None:
        key = self._build_key(conversation_id)

        try:
            await self._redis.delete(key)
        except RedisError as exc:
            logger.exception(
                "Failed to delete conversation state",
                extra={
                    "event": "conversation_state_delete_failed",
                    "conversation_id": conversation_id,
                },
            )
            raise ConversationStorageError(
                "Unable to delete conversation state."
            ) from exc
