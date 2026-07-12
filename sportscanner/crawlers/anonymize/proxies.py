import os

import httpx

from sportscanner.variables import settings


def httpxAsyncClientWithProxyRotation() -> httpx.AsyncClient:
    # httpx 0.28 dropped the per-scheme `proxies={"http://": ..., "https://": ...}`
    # dict mapping in favour of a single `proxy=` string (use `mounts=` instead if
    # http/https ever need genuinely different proxies) - this was broken (raised
    # TypeError on the removed `proxies` kwarg) until it was actually exercised for
    # the first time by a provider-level `_http_client()` override, since
    # `USE_PROXIES` has always defaulted to False and this path was otherwise dead.
    return httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.HTTPX_CLIENT_MAX_CONNECTIONS,
            max_keepalive_connections=settings.HTTPX_CLIENT_MAX_KEEPALIVE_CONNECTIONS,
        ),
        timeout=httpx.Timeout(
            timeout=settings.HTTPX_CLIENT_TIMEOUT,
            connect=10.0,  # Max time to establish a connection
            read=10.0,  # Max time to read a response
        ),
        proxy=settings.ROTATING_PROXY_ENDPOINT,
    )


def httpxAsyncClientWithoutProxyRotation() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.HTTPX_CLIENT_MAX_CONNECTIONS,
            max_keepalive_connections=settings.HTTPX_CLIENT_MAX_KEEPALIVE_CONNECTIONS,
        ),
        timeout=httpx.Timeout(
            timeout=settings.HTTPX_CLIENT_TIMEOUT,
            connect=10.0,  # Max time to establish a connection
            read=10.0,  # Max time to read a response
        ),
        # Transparently retries connection-level failures (DNS blips, resets,
        # dropped connections) - does not retry on HTTP error status codes.
        transport=httpx.AsyncHTTPTransport(retries=2),
    )


# Conditional function that returns the appropriate client
def httpxAsyncClient() -> httpx.AsyncClient:
    return (
        httpxAsyncClientWithProxyRotation()
        if settings.USE_PROXIES
        else httpxAsyncClientWithoutProxyRotation()
    )
