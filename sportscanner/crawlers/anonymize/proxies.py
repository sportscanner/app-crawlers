import os
from typing import Any, Dict, Optional

import httpx

from sportscanner.logger import logging
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


async def get_with_proxy_fallback_on_403(
        client: httpx.AsyncClient,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
        timeout: float = 30,
        max_proxy_attempts: int = 4,
        log_label: str = "",
) -> Optional[httpx.Response]:
    """GET `url` via `client` first; on HTTP 403, retry against fresh rotating-proxy
    connections (`max_proxy_attempts` times) before giving up.

    A 403 through a direct connection can mean this host's IP is blocklisted for
    this specific target - confirmed for a handful of Matchi/Playtomic padel
    venues, all-or-nothing per GitHub Actions run (each run gets one fresh
    runner IP; whether that IP happens to already be blocklisted for a given
    venue's WAF is independent per venue/provider - see docs/clubs/matchi.md
    and docs/clubs/playtomic.md). Each fresh proxied connection is a fresh shot
    at a different exit IP - Webshare's rotation happens at connection setup,
    not per-request within one kept-alive connection, so retrying against a
    *reused* client would not help (same reasoning as Everyone Active's retry,
    see docs/clubs/everyone-active.md, which needs the proxy on every attempt
    from the start rather than as a 403 fallback, since it's blocked ~100% of
    the time rather than for a handful of specific venues).

    Any non-403 HTTP error is raised immediately - a 403 is the only signal
    specific to this failure mode; other errors mean something else entirely
    and retrying via proxy wouldn't help.

    Returns the successful response, or `None` if every proxy attempt also 403'd.
    """
    try:
        resp = await client.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 403:
            raise

    last_status = 403
    for attempt in range(1, max_proxy_attempts + 1):
        try:
            async with httpxAsyncClientWithProxyRotation() as proxied_client:
                resp = await proxied_client.get(url, params=params, headers=headers, timeout=timeout)
                resp.raise_for_status()
                return resp
        except httpx.HTTPStatusError as exc:
            last_status = exc.response.status_code
            if last_status != 403:
                raise
            logging.debug(f"{log_label}: 403 via proxy, attempt {attempt}/{max_proxy_attempts}")
    logging.warning(
        f"{log_label}: exhausted {max_proxy_attempts} proxy attempts after direct 403 "
        f"- this run's IP may be blocklisted for this target"
    )
    return None
