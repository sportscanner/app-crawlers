"""For fetching environment variables used across all modules"""

import os
from pathlib import Path as _Path
from typing import Optional
from urllib.parse import urljoin

from pydantic import BaseModel, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich import print

# Resolve env files relative to app-crawlers root so settings load correctly
# regardless of the current working directory used to launch the server.
APP_CRAWLERS_ROOT = _Path(__file__).resolve().parents[1]
env_file_name = ".env" if os.getenv("ENV") == "prod" else ".dev.env"
env_file_path = APP_CRAWLERS_ROOT / env_file_name


class Settings(BaseSettings):
    DB_CONNECTION_STRING: str
    HTTPX_CLIENT_MAX_CONNECTIONS: int
    HTTPX_CLIENT_MAX_KEEPALIVE_CONNECTIONS: int
    HTTPX_CLIENT_TIMEOUT: float
    USE_PROXIES: bool = False
    ROTATING_PROXY_ENDPOINT: str
    API_BASE_URL: Optional[str] = "http://localhost:8000/"
    CLOUD_FIRESTORE_CREDENTIALS_PATH: Optional[str]
    CLOUD_FIRESTORE_PROJECT_ID: Optional[str]
    FIRESTORE_USER_COLLECTION: Optional[str] = "users"
    JWT_SECRET: str
    JWT_ALGORITHM: str
    ENV: str
    KINDE_DOMAIN: str
    KINDE_CLIENT_ID: str
    OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    SPORTSCANNER_AGENT_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    SPORTSCANNER_AGENT_MODEL: str = "openrouter/google/gemini-3-flash-preview"
    SPORTSCANNER_JUDGE_MODEL: Optional[str] = None
    SPORTSCANNER_MCP_SERVER_URL: Optional[str] = None
    OTEL_EXPORTER_ENDPOINT: Optional[str] = None
    OTEL_PROJECT_ID: Optional[str] = "sportscanner-backend"

    model_config = SettingsConfigDict(
        env_file=env_file_path, env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
