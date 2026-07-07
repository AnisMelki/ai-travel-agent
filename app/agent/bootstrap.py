from openai import AsyncOpenAI
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from app.core.config import get_settings


def bootstrap_agent():
    settings = get_settings()
    client = AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        timeout=settings.LLM_TIME_OUT,
        max_retries=settings.LLM_MAX_RETRY,
    )
    model = OpenAIChatCompletionsModel(
        openai_client=client,
        model=settings.OPENROUTER_MODEL,
    )
    return model
