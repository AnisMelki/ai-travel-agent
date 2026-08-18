import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import RedisError

from app.repositories.redis_conversation_repository import (
    ConversationStorageError,
    RedisConversationRepository,
)
from app.schema.state_conversation import FlightConversationState


def _make_state(**overrides) -> FlightConversationState:
    defaults = dict(
        conversation_id="conv-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return FlightConversationState(**defaults)


def _make_repository(redis_client) -> RedisConversationRepository:
    return RedisConversationRepository(redis_client=redis_client, ttl_seconds=3600)


def test_get_returns_none_when_key_missing():
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=None)
    repository = _make_repository(redis_client)

    result = asyncio.run(repository.get("conv-1"))

    assert result is None
    redis_client.get.assert_awaited_once_with("flight:conversation:conv-1")


def test_get_returns_deserialized_state_when_present():
    state = _make_state()
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=state.model_dump_json())
    repository = _make_repository(redis_client)

    result = asyncio.run(repository.get("conv-1"))

    assert result == state


def test_get_raises_conversation_storage_error_on_redis_error():
    redis_client = MagicMock()
    redis_error = RedisError("connection lost")
    redis_client.get = AsyncMock(side_effect=redis_error)
    repository = _make_repository(redis_client)

    with pytest.raises(ConversationStorageError) as exc_info:
        asyncio.run(repository.get("conv-1"))

    assert exc_info.value.__cause__ is redis_error


def test_get_raises_conversation_storage_error_on_invalid_json():
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value="not valid json")
    repository = _make_repository(redis_client)

    with pytest.raises(ConversationStorageError):
        asyncio.run(repository.get("conv-1"))


def test_save_sends_serialized_state_with_ttl():
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=True)
    repository = _make_repository(redis_client)
    state = _make_state()

    asyncio.run(repository.save(state))

    redis_client.set.assert_awaited_once_with(
        name="flight:conversation:conv-1",
        value=state.model_dump_json(),
        ex=3600,
    )


def test_save_raises_conversation_storage_error_on_redis_error():
    redis_client = MagicMock()
    redis_error = RedisError("connection lost")
    redis_client.set = AsyncMock(side_effect=redis_error)
    repository = _make_repository(redis_client)

    with pytest.raises(ConversationStorageError) as exc_info:
        asyncio.run(repository.save(_make_state()))

    assert exc_info.value.__cause__ is redis_error


def test_save_raises_conversation_storage_error_on_serialization_error():
    redis_client = MagicMock()
    redis_client.set = AsyncMock()
    repository = _make_repository(redis_client)

    broken_state = MagicMock()
    broken_state.conversation_id = "conv-1"
    broken_state.version = 0
    serialization_error = ValueError("cannot serialize")
    broken_state.model_dump_json = MagicMock(side_effect=serialization_error)

    with pytest.raises(ConversationStorageError) as exc_info:
        asyncio.run(repository.save(broken_state))

    assert exc_info.value.__cause__ is serialization_error
    redis_client.set.assert_not_awaited()


def test_delete_removes_key():
    redis_client = MagicMock()
    redis_client.delete = AsyncMock(return_value=1)
    repository = _make_repository(redis_client)

    asyncio.run(repository.delete("conv-1"))

    redis_client.delete.assert_awaited_once_with("flight:conversation:conv-1")


def test_delete_raises_conversation_storage_error_on_redis_error():
    redis_client = MagicMock()
    redis_error = RedisError("connection lost")
    redis_client.delete = AsyncMock(side_effect=redis_error)
    repository = _make_repository(redis_client)

    with pytest.raises(ConversationStorageError) as exc_info:
        asyncio.run(repository.delete("conv-1"))

    assert exc_info.value.__cause__ is redis_error
