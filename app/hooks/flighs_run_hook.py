from __future__ import annotations

import logging
import time
from typing import Any

from agents import Agent, RunContextWrapper, RunHooks
from agents.items import ModelResponse, TResponseInputItem
from agents.lifecycle import AgentHookContext
from agents.tool import Tool

from app.context.flight_context import FlightAgentContext

logger = logging.getLogger(__name__)


class FlightRunHooks(RunHooks[FlightAgentContext]):
    """
    Production lifecycle hooks for the complete FlightAgent run.

    Important:
        Create one FlightRunHooks instance per Runner.run() execution.
        Do not share the same stateful instance between concurrent requests.
    """

    def __init__(self) -> None:
        self._run_started_at: float | None = None
        self._llm_started_at: dict[str, float] = {}
        self._tool_started_at: dict[str, list[float]] = {}
        self._agent_started_at: dict[str, float] = {}

    async def on_agent_start(
        self,
        context: AgentHookContext[FlightAgentContext],
        agent: Agent[FlightAgentContext],
    ) -> None:
        if self._run_started_at is None:
            self._run_started_at = time.perf_counter()

        self._agent_started_at[agent.name] = time.perf_counter()

        logger.info(
            "Agent started",
            extra={
                "event": "agent_start",
                "agent_name": agent.name,
            },
        )

    async def on_agent_end(
        self,
        context: AgentHookContext[FlightAgentContext],
        agent: Agent[FlightAgentContext],
        output: Any,
    ) -> None:
        duration_ms = self._elapsed_ms(self._run_started_at)
        usage = context.usage

        logger.info(
            "Agent completed",
            extra={
                "event": "agent_end",
                "agent_name": agent.name,
                "duration_ms": duration_ms,
                "output_type": type(output).__name__,
                "model_requests": getattr(usage, "requests", None),
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            },
        )

    async def on_llm_start(
        self,
        context: RunContextWrapper[FlightAgentContext],
        agent: Agent[FlightAgentContext],
        system_prompt: str | None,
        input_items: list[TResponseInputItem],
    ) -> None:
        key = self._llm_key(agent)
        self._llm_started_at[key] = time.perf_counter()

        logger.debug(
            "LLM call started",
            extra={
                "event": "llm_start",
                "agent_name": agent.name,
                "input_item_count": len(input_items),
                "has_system_prompt": system_prompt is not None,
            },
        )

    async def on_llm_end(
        self,
        context: RunContextWrapper[FlightAgentContext],
        agent: Agent[FlightAgentContext],
        response: ModelResponse,
    ) -> None:
        key = self._llm_key(agent)
        started_at = self._llm_started_at.pop(key, None)

        logger.info(
            "LLM call completed",
            extra={
                "event": "llm_end",
                "agent_name": agent.name,
                "duration_ms": self._elapsed_ms(started_at),
                "output_item_count": len(response.output),
            },
        )

    async def on_tool_start(
        self,
        context: RunContextWrapper[FlightAgentContext],
        agent: Agent[FlightAgentContext],
        tool: Tool,
    ) -> None:
        self._tool_started_at.setdefault(tool.name, []).append(time.perf_counter())

        logger.info(
            "Tool started",
            extra={
                "event": "tool_start",
                "agent_name": agent.name,
                "tool_name": tool.name,
            },
        )

    async def on_tool_end(
        self,
        context: RunContextWrapper[FlightAgentContext],
        agent: Agent[FlightAgentContext],
        tool: Tool,
        result: object,
    ) -> None:
        pending = self._tool_started_at.get(tool.name)
        started_at = pending.pop() if pending else None
        if pending is not None and not pending:
            del self._tool_started_at[tool.name]

        logger.info(
            "Tool completed",
            extra={
                "event": "tool_end",
                "agent_name": agent.name,
                "tool_name": tool.name,
                "duration_ms": self._elapsed_ms(started_at),
                "result_type": type(result).__name__,
                "result_size": self._safe_result_size(result),
            },
        )

    async def on_handoff(
        self,
        context: RunContextWrapper[FlightAgentContext],
        from_agent: Agent[FlightAgentContext],
        to_agent: Agent[FlightAgentContext],
    ) -> None:
        logger.info(
            "Agent handoff",
            extra={
                "event": "agent_handoff",
                "from_agent": from_agent.name,
                "to_agent": to_agent.name,
            },
        )

    @staticmethod
    def _elapsed_ms(started_at: float | None) -> float | None:
        if started_at is None:
            return None

        return round((time.perf_counter() - started_at) * 1000, 2)

    @staticmethod
    def _llm_key(agent: Agent[FlightAgentContext]) -> str:
        return agent.name

    @staticmethod
    def _safe_result_size(result: object) -> int | None:
        """
        Returns useful size metadata without serializing or logging
        the complete tool result.
        """
        if isinstance(result, (str, bytes, list, tuple, set, dict)):
            return len(result)

        results = getattr(result, "results", None)
        if isinstance(results, list):
            return len(results)

        reviews = getattr(result, "reviews", None)
        if isinstance(reviews, dict):
            return sum(
                len(items) for items in reviews.values() if isinstance(items, list)
            )
        return None
