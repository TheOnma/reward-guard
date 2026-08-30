from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    judge_provider: str = "anthropic"
    judge_model: str = "claude-sonnet-4-5"
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
