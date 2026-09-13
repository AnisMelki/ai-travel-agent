import logging

from app.observability.llm_metrics import LLMCallMetrics

logger = logging.getLogger(__name__)


def log_llm_metrics(metrics: LLMCallMetrics) -> None:
    logger.info(
        "LLM call completed",
        extra={
            "event": "llm_call_completed",
            **metrics.model_dump(),
        },
    )
