from pydantic_settings import BaseSettings, SettingsConfigDict
import logging
import sys

from pythonjsonlogger.json import JsonFormatter


class Settings(BaseSettings):
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str
    OPENROUTER_MODEL: str
    LLM_TIME_OUT: int
    LLM_MAX_RETRY: int
    APIFY_API_TOKEN: str
    REDIS_URL: str
    REDIS_CONVERSATION_TTL_SECONDS: int
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()  # type: ignore[call-arg]


def get_settings() -> Settings:
    return settings


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)

    formatter = JsonFormatter(
        fmt=("%(asctime)s %(levelname)s %(name)s %(message)s"),
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
        },
        timestamp=True,
    )

    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    # Évite que les logs Uvicorn soient affichés deux fois.
    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # Les bibliothèques tierces restent moins verbeuses
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
