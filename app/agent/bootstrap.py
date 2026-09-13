import logging

from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from apify_client import ApifyClientAsync
from fastapi import FastAPI
from langfuse import Langfuse
from openai import AsyncOpenAI
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.agent.flight_agent import create_flight_agent, create_flights_agent_selection
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class BootstrapRedis:
    def __init__(self):
        self.settings = get_settings()
        self.redis: Redis | None = None

    @property
    def client(self) -> Redis:
        if self.redis is None:
            raise RuntimeError("Redis client has not been initialized.")
        return self.redis

    async def startup(self):
        redis = Redis.from_url(
            self.settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )

        try:
            await redis.ping()
            logger.info("Connected to Redis successfully")
        except RedisError as e:
            logger.exception(
                "Failed to connect to Redis",
                extra={
                    "event": "redis_connection_failed",
                    "error": str(e),
                },
            )
            await redis.aclose()
            raise
        self.redis = redis

    async def shutdown(self):
        if self.redis is not None:
            await self.redis.aclose()
            self.redis = None


class BootstrapAgent:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model: OpenAIChatCompletionsModel | None = None
        self._client: AsyncOpenAI | None = None

    @property
    def model(self) -> OpenAIChatCompletionsModel:
        if self._model is None:
            raise RuntimeError("LLM model has not been initialized.")
        return self._model

    async def startup(self) -> None:
        self._client = AsyncOpenAI(
            api_key=self.settings.OPENROUTER_API_KEY,
            base_url=self.settings.OPENROUTER_BASE_URL,
            timeout=self.settings.LLM_TIME_OUT,
            max_retries=self.settings.LLM_MAX_RETRY,
        )

        self._model = OpenAIChatCompletionsModel(
            openai_client=self._client,
            model=self.settings.OPENROUTER_MODEL,
        )
        logger.info("LLM model initialized successfully")

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._model = None


class BootstrapApify:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: ApifyClientAsync | None = None

    @property
    def client(self) -> ApifyClientAsync:
        if self._client is None:
            raise RuntimeError("Apify client has not been initialized.")
        return self._client

    async def startup(self) -> None:
        self._client = ApifyClientAsync(self.settings.APIFY_API_TOKEN)
        logger.info("Apify client initialized successfully")


class BootstrapLangfuse:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Langfuse | None = None

    @property
    def client(self) -> Langfuse:
        if self._client is None:
            raise RuntimeError("Langfuse client has not been initialized.")
        return self._client

    async def startup(self) -> None:
        # Instrument the OpenAI Agents SDK before any Agent/Runner call so every
        # generation, tool call, and handoff is captured as an OTel span.
        OpenAIAgentsInstrumentor().instrument()

        self._client = Langfuse(
            public_key=self.settings.LANGFUSE_PUBLIC_KEY,
            secret_key=self.settings.LANGFUSE_SECRET_KEY,
            base_url=self.settings.LANGFUSE_BASE_URL,
            environment=self.settings.LANGFUSE_ENVIRONMENT,
        )

        if self._client.auth_check():
            logger.info("Langfuse client initialized and authenticated successfully")
        else:
            logger.warning(
                "Langfuse client initialized but authentication check failed;"
                " check LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY/LANGFUSE_BASE_URL"
            )

    async def shutdown(self) -> None:
        if self._client is not None:
            self._client.flush()
            self._client = None


class BootstrapApplication:
    def __init__(self):
        self.agent_bootstrap = BootstrapAgent()
        self.redis_bootstrap = BootstrapRedis()
        self.apify_bootstrap = BootstrapApify()
        self.langfuse_bootstrap = BootstrapLangfuse()

    async def startup(self, app: FastAPI) -> None:
        try:
            await self.langfuse_bootstrap.startup()
            await self.agent_bootstrap.startup()
            await self.redis_bootstrap.startup()
            await self.apify_bootstrap.startup()
            model = self.agent_bootstrap.model
            app.state.flight_agent = create_flight_agent(model)
            app.state.selection_agent = create_flights_agent_selection(model)
            app.state.redis = self.redis_bootstrap.client
            app.state.apify_client = self.apify_bootstrap.client
            app.state.langfuse_client = self.langfuse_bootstrap.client
        except Exception:
            logger.exception("Application startup failed")
            await self.shutdown()
            raise

    async def shutdown(self):
        await self.redis_bootstrap.shutdown()
        await self.agent_bootstrap.shutdown()
        await self.langfuse_bootstrap.shutdown()
