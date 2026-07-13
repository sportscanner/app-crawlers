"""For fetching environment variables used across all modules"""

import os
from typing import Optional
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
    # Valkey (Redis-protocol-compatible) cache for near-static lookups (postcode
    # geocoding, venues-within-radius). Optional — caching is skipped entirely if unset.
    VALKEY_URL: Optional[str] = None
    CACHE_TTL_SECONDS: int = 300
    # Public origin the MCP server's OAuth proxy is reachable at. Must be the
    # true domain root (no "/mcp" suffix) — the proxy builds its OAuth routes
    # (redirect callback, /token, /authorize) and RFC 9728 protected-resource
    # metadata relative to this, and that metadata is required to live at the
    # origin root regardless of where the MCP JSON-RPC endpoint itself sits.
    MCP_PUBLIC_BASE_URL: str = "https://api.sportscanner.co.uk"

    # Stripe Connect (Express accounts) — powers organizer payouts for the Games
    # feature. Optional so the app still boots for engineers without Stripe test
    # keys configured; endpoints that need them raise a clear 500 instead.
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    # Origin the frontend is reachable at, used to build Stripe Connect
    # onboarding return/refresh URLs (e.g. https://beta.sportscanner.co.uk).
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    # Platform fee taken out of every game payment before the rest is routed to
    # the organizer's connected account, expressed as percent + a fixed pence
    # amount (mirrors Eventbrite/Meetup-style organizer fees — intentionally not
    # a token/trivial amount). E.g. 8% + 20p on a £10 join = 80p + 20p = £1.00 fee.
    PLATFORM_FEE_PERCENT: float = 8.0
    PLATFORM_FEE_FIXED_PENCE: int = 20

    model_config = SettingsConfigDict(env_file=env_file, env_file_encoding="utf-8", extra="ignore")


settings = Settings()
