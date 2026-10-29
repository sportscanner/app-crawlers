"""For fetching environment variables used across all modules"""

import os
from typing import Literal, Optional
from urllib.parse import urljoin

from pydantic import BaseModel, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich import print

# Check for an environment variable to determine the environment
env_file = ".env" if os.getenv("ENV") == "prod" else ".dev.env"


class Settings(BaseSettings):
    DB_CONNECTION_STRING: str
    HTTPX_CLIENT_MAX_CONNECTIONS: int
    HTTPX_CLIENT_MAX_KEEPALIVE_CONNECTIONS: int
    HTTPX_CLIENT_TIMEOUT: float
    CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER: int = 20
    # Playtomic padel is switched off: the many Playtomic venues added recently
    # make the padel crawl so slow that it stalls and drags down the other
    # padel providers. Set PLAYTOMIC_PADEL_ENABLED=true to bring it back.
    PLAYTOMIC_PADEL_ENABLED: bool = False
    # Per-process database pool. The API keeps the default (5 total); parallel
    # crawler containers override this to 1 + 1 so five sports plus the API stay
    # under Aiven's 20-connection limit.
    DB_POOL_SIZE: int = 3
    DB_MAX_OVERFLOW: int = 2
    API_BASE_URL: Optional[str] = "http://localhost:8000/"
    CLOUD_FIRESTORE_CREDENTIALS_PATH: Optional[str]
    CLOUD_FIRESTORE_PROJECT_ID: Optional[str]
    FIRESTORE_USER_COLLECTION: Optional[str] = "users"
    JWT_SECRET: str
    JWT_ALGORITHM: str
    ENV: str
    KINDE_DOMAIN: str
    KINDE_CLIENT_ID: str
    # Valkey (Redis-protocol-compatible) cache for near-static lookups (postcode
    # geocoding, venues-within-radius). Optional — caching is skipped entirely if unset.
    VALKEY_URL: Optional[str] = None
    CACHE_TTL_SECONDS: int = 300
    # Public API origin used in discovery links (no /mcp suffix).
    # Retain the environment variable name for deployment compatibility.
    MCP_PUBLIC_BASE_URL: str = "https://api.sportscanner.co.uk"
    # A2A Sportscanner Agent (sportscanner/agents/a2a). The LLM is reached
    # through an OpenAI-compatible API: OpenRouter (default) or OpenCode.
    # A2A_MODEL uses the selected provider's model ids. Without a key the
    # agent card is still served, but tasks fail with a clear error.
    A2A_LLM_PROVIDER: Literal["openrouter", "opencode"] = "openrouter"
    A2A_MODEL: str = "deepseek/deepseek-v4.1-flash"
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENCODE_API_KEY: Optional[str] = None
    OPENCODE_BASE_URL: str = "https://opencode.ai/inference/openai/v1"
    # Every A2A message costs an LLM call, so callers must present a
    # Sportscanner API token (ssc_...) or Kinde access token by default.
    A2A_REQUIRE_AUTH: bool = True
    # The website's Agent mode (POST /agent/chat) runs the same agent. Signed-in
    # users send their Kinde refresh token (like /user); signed-out homepage
    # visitors are allowed with a tighter per-IP limit. REQUIRE_AUTH=false
    # skips identity checks entirely (local dev only).
    AGENT_CHAT_REQUIRE_AUTH: bool = True
    AGENT_CHAT_ALLOW_ANONYMOUS: bool = True
    AGENT_CHAT_MESSAGES_PER_HOUR: int = 40
    AGENT_CHAT_ANON_MESSAGES_PER_HOUR: int = 10

    model_config = SettingsConfigDict(
        env_file=env_file, env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
