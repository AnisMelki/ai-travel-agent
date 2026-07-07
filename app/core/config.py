from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str
    OPENROUTER_MODEL: str
    LLM_TIME_OUT: int
    LLM_MAX_RETRY: int
    APIFY_API_TOKEN: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


@lru_cache
def get_settings() -> Settings:
    return settings


def get_settinf() -> Settings:
    return get_settings()
