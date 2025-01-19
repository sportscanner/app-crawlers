import httpx
import os

from sqlalchemy import false

ROTATING_PROXY_ENDPOINT = os.getenv("ROTATING_PROXY_ENDPOINT")
HTTPX_CLIENT_MAX_CONNECTIONS = os.getenv("HTTPX_CLIENT_MAX_CONNECTIONS")
HTTPX_CLIENT_MAX_KEEPALIVE_CONNECTIONS = os.getenv("HTTPX_CLIENT_MAX_KEEPALIVE_CONNECTIONS")
HTTPX_CLIENT_TIMEOUT = os.getenv("HTTPX_CLIENT_TIMEOUT")
USE_PROXIES: bool = os.getenv("USE_PROXIES", False)

proxies = {
    "http://": ROTATING_PROXY_ENDPOINT,
    "https://": ROTATING_PROXY_ENDPOINT,
}

def httpxAsyncClientWithProxyRotation() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        limits=httpx.Limits(max_connections=250, max_keepalive_connections=20),
        timeout=httpx.Timeout(timeout=15.0),
        proxies=proxies
    )


def httpxAsyncClientWithoutProxyRotation() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        limits=httpx.Limits(max_connections=250, max_keepalive_connections=20),
        timeout=httpx.Timeout(timeout=15.0)
    )


# Conditional function that returns the appropriate client
def httpxAsyncClient() -> httpx.AsyncClient:
    return (
        httpxAsyncClientWithProxyRotation()
        if USE_PROXIES
        else httpxAsyncClientWithoutProxyRotation()
    )

