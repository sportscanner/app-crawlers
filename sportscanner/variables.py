"""For fetching environment variables used across all modules"""

import os
from typing import Optional
from urllib.parse import urljoin

from pydantic import BaseModel, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich import print

# Check for an environment variable to determine the environment
env_file = ".env" if os.getenv("ENV") == "prod" else "dev.env"


class Settings(BaseSettings):
    DB_CONNECTION_STRING: str
    SQL_DATABASE_NAME: str
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

    model_config = SettingsConfigDict(env_file=env_file, env_file_encoding="utf-8")


settings = Settings()
