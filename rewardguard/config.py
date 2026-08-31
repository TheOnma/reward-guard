from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    judge_provider: str = "anthropic"
    judge_model: str = "claude-sonnet-5"
    host: str = "0.0.0.0"
    port: int = 8000
    # Opt-in workaround for a broken local DNS resolver. Comma-separated host=ip pairs,
    # e.g. "api.openai.com=172.66.0.243". Empty = no override (the normal case).
    dns_override: str = ""


settings = Settings()
