from typing import Any

from pydantic import BaseModel, Field


class LLMCallMetrics(BaseModel):
    conversation_id: str
    agent_name: str
    model: str

    latency_ms: float

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    success: bool
    retry_count: int = 0
    error_type: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
