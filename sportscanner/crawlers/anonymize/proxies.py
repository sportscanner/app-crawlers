import os
from typing import Any, Dict, Optional

import httpx
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import HTTPError as CurlHTTPError

from sportscanner.logger import logging
from sportscanner.variables import settings

# Browser TLS fingerprint used for the free WAF retry stage. Playtomic, Matchi
# and ClubSpark sit behind Cloudflare-style bot checks that score the TLS
# handshake: Python's httpx/ssl handshake fails from datacenter IPs (GitHub
# Actions runners) with an immediate 403 even when the same request succeeds
# from residential IPs. curl_cffi replays a genuine Chrome handshake, which is
# the same fix CitySport needed (see docs/clubs/citysport.md). This stage costs
# nothing and runs before the paid rotating-proxy stage, which keeps proxy
# tier usage near zero for these providers.
_IMPERSONATE = "chrome124"


def httpxAsyncClientWithProxyRotation(force_proxy: bool = False) -> httpx.AsyncClient:
    # httpx 0.28 dropped the per-scheme `proxies={"http://": ..., "https://": ...}`
    # dict mapping in favour of a single `proxy=` string (use `mounts=` instead if
    # http/https ever need genuinely different proxies) - this was broken (raised
    # TypeError on the removed `proxies` kwarg) until it was actually exercised for
    # the first time by a provider-level `_http_client()` override, since
    # `USE_PROXIES` has always defaulted to False and this path was otherwise dead.
    #
    # `USE_PROXIES` is the single global kill switch: Everyone Active, UEL
    # SportsDock, and the Matchi/Playtomic 403-fallback all route through this
    # function rather than checking the setting themselves, so gating it here
    # (instead of at each call site) is what makes `USE_PROXIES=False` actually
    # stop every proxied request, not just the ones going through the shared
    # BaseCrawler client.
    if not settings.USE_PROXIES and not force_proxy:
        return httpxAsyncClientWithoutProxyRotation()
    if not settings.ROTATING_PROXY_ENDPOINT:
        return httpxAsyncClientWithoutProxyRotation()
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
) -> Optional[Any]:
    """GET `url` via `client` first; on HTTP 403 or 429 (bot challenge / rate limit),
    retry via curl_cffi with a browser TLS fingerprint (free), then via fresh
    rotating-proxy connections (`max_proxy_attempts` times) before giving up.

    Retry chain, cheapest first:
    1. Direct httpx request (as before).
    2. curl_cffi with `impersonate="chrome124"` - replays a genuine browser TLS
       handshake. Cloudflare-style WAFs (Playtomic, Matchi, ClubSpark) score the
       handshake itself, and httpx's Python-ssl handshake is an automatic fail
       from datacenter IPs such as GitHub Actions runners even when the target
       IP is not blocklisted. Same fix CitySport needed (docs/clubs/citysport.md).
    3. Rotating proxy attempts (only burns paid tier if stages 1-2 both failed).

    A 403 or 429 through a direct connection can mean this host's IP is blocklisted or
    rate-limited by Cloudflare / WAF for this specific target - confirmed for a handful of
    Matchi/Playtomic padel venues and ClubSpark tennis venues, all-or-nothing per GitHub Actions
    run (each run gets one fresh runner IP; whether that IP happens to already be blocklisted
    for a given venue's WAF is independent per venue/provider). Each fresh proxied connection
    is a fresh shot at a different exit IP - Webshare's rotation happens at connection setup,
    not per-request within one kept-alive connection, so retrying against a *reused* client
    would not help.

    Any other non-403/429 HTTP error is raised immediately.

    Returns the successful response (httpx or curl_cffi - both expose .json() /
    .text / .status_code), or `None` if every retry stage also failed with 403/429.
    """
    try:
        resp = await client.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in (403, 429):
            raise
        last_status = exc.response.status_code

    # Stage 2: free browser-TLS retry via curl_cffi (no proxy involved).
    for attempt in range(1, 3):
        try:
            async with AsyncSession() as impersonated:
                resp = await impersonated.get(
                    url,
                    params=params,
                    headers=headers,
                    impersonate=_IMPERSONATE,
                    timeout=timeout,
                )
            if resp.status_code in (403, 429):
                last_status = resp.status_code
                logging.debug(
                    f"{log_label}: {last_status} via TLS impersonation, attempt {attempt}/2"
                )
                continue
            return resp
        except CurlHTTPError as exc_tls:
            status = (
                exc_tls.response.status_code if exc_tls.response is not None else None
            )
            if status not in (403, 429):
                raise
            last_status = status
            logging.debug(
                f"{log_label}: {last_status} via TLS impersonation, attempt {attempt}/2"
            )
        except Exception as exc_tls_unexpected:
            logging.debug(
                f"{log_label}: TLS-impersonation attempt {attempt}/2 failed: "
                f"{type(exc_tls_unexpected).__name__}: {exc_tls_unexpected!r}"
            )

    for attempt in range(1, max_proxy_attempts + 1):
        try:
            async with httpxAsyncClientWithProxyRotation(
                force_proxy=True
            ) as proxied_client:
                resp = await proxied_client.get(
                    url, params=params, headers=headers, timeout=timeout
                )
                resp.raise_for_status()
                return resp
        except httpx.HTTPStatusError as exc_proxy:
            last_status = exc_proxy.response.status_code
            if last_status not in (403, 429):
                raise
            logging.debug(
                f"{log_label}: {last_status} via proxy, attempt {attempt}/{max_proxy_attempts}"
            )
    logging.warning(
        f"{log_label}: exhausted direct + TLS-impersonation + {max_proxy_attempts} proxy attempts "
        f"- this run's IP may be blocklisted for this target"
    )
    return None
