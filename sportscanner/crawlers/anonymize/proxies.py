import os

import httpx

from sportscanner.variables import settings

proxies = {
    "http://": settings.ROTATING_PROXY_ENDPOINT,
    "https://": settings.ROTATING_PROXY_ENDPOINT,
}


def httpxAsyncClientWithProxyRotation() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.HTTPX_CLIENT_MAX_CONNECTIONS,
            max_keepalive_connections=settings.HTTPX_CLIENT_MAX_KEEPALIVE_CONNECTIONS,
        ),
        timeout=httpx.Timeout(timeout=settings.HTTPX_CLIENT_TIMEOUT),
        proxies=proxies,
    )


def httpxAsyncClientWithoutProxyRotation() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.HTTPX_CLIENT_MAX_CONNECTIONS,
            max_keepalive_connections=settings.HTTPX_CLIENT_MAX_KEEPALIVE_CONNECTIONS,
        ),
        timeout=httpx.Timeout(timeout=settings.HTTPX_CLIENT_TIMEOUT),
    )


# Conditional function that returns the appropriate client
def httpxAsyncClient() -> httpx.AsyncClient:
    return (
        httpxAsyncClientWithProxyRotation()
        if settings.USE_PROXIES
        else httpxAsyncClientWithoutProxyRotation()
    )
