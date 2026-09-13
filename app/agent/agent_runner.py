from dataclasses import dataclass
from time import perf_counter

from agents import Agent, Runner, RunResult
from agents.exceptions import ModelBehaviorError
from langfuse import get_client

from app.core.config import settings
from app.hooks.flighs_run_hook import UsageRunHooks
from app.observability.llm_logger import log_llm_metrics
from app.observability.llm_metrics import LLMCallMetrics


@dataclass
class AgentRunResult:
    result: RunResult
    metrics: LLMCallMetrics


async def run_agent_with_retry(
    agent: Agent,
    message: str,
    *,
    context: object,
    max_retries: int = 1,
    hooks: UsageRunHooks | None = None,
    conversation_id: str,
) -> AgentRunResult:
    start_time = perf_counter()
    retry_count = 0
    run_hooks = hooks or UsageRunHooks()
    langfuse = get_client()

    while True:
        with langfuse.start_as_current_observation(
            as_type="agent",
            name="agent_run",
            input={
                "message": message,
                "conversation_id": conversation_id,
            },
        ) as span:
            try:
                run = await Runner.run(
                    agent,
                    message,
                    context=context,
                    hooks=run_hooks,
                )
            except ModelBehaviorError as exc:
                span.update(level="ERROR", status_message=str(exc))

                if retry_count >= max_retries:
                    latency_ms = (perf_counter() - start_time) * 1000

                    metrics = LLMCallMetrics(
                        conversation_id=conversation_id,
                        agent_name=agent.name,
                        model=settings.OPENROUTER_MODEL,
                        latency_ms=latency_ms,
                        success=False,
                        retry_count=retry_count,
                        input_tokens=run_hooks.input_tokens,
                        output_tokens=run_hooks.output_tokens,
                        total_tokens=run_hooks.total_tokens,
                        error_type=type(exc).__name__,
                    )

                    log_llm_metrics(metrics)

                    raise

                retry_count += 1
                continue

            latency_ms = (perf_counter() - start_time) * 1000

            metrics = LLMCallMetrics(
                conversation_id=conversation_id,
                agent_name=agent.name,
                model=settings.OPENROUTER_MODEL,
                latency_ms=latency_ms,
                success=True,
                retry_count=retry_count,
                input_tokens=run_hooks.input_tokens,
                output_tokens=run_hooks.output_tokens,
                total_tokens=run_hooks.total_tokens,
            )
            log_llm_metrics(metrics)
            span.update(
                output={
                    "metrics": metrics.model_dump_json(),
                }
            )

            return AgentRunResult(
                result=run,
                metrics=metrics,
            )
