from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr
from typing import Literal


class Settings(BaseSettings):

    # Application environment
    environment: Literal["development", "testing", "production"] = "development"
    # MongoDB
    mongodb_uri: SecretStr
    database_name: str

    # Groq
    groq_api_key: SecretStr
    groq_model: str

    # JWT
    jwt_secret_key: SecretStr
    jwt_algorithm: str
    access_token_expire_minutes: int = Field(gt=0)
    refresh_token_expire_days: int = Field(gt=0)

    # Redis
    redis_url: SecretStr

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


settings = Settings()   