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
# the same fix CitySport needed (see docs/clubs/citysport.md).
_IMPERSONATE = "chrome124"

# The paid rotating-proxy integration (Webshare) was removed in August 2026:
# the subscription's bandwidth cap was being burned on 403 retries that the
# proxy could not rescue anyway (Cloudflare was IP-blocking the proxy exits as
# well as the runner range). The free curl_cffi TLS-impersonation stage below
# is the only WAF workaround now. If a provider ever genuinely needs a
# different egress IP again, reintroduce it as a provider-specific concern
# rather than a global fallback.


def httpxAsyncClient() -> httpx.AsyncClient:
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


# Backwards-compatible alias: several providers (Everyone Active, UEL
# SportsDock) historically imported the proxy-rotating client factory. The
# proxy is gone, so this is now just the direct client.
def httpxAsyncClientWithProxyRotation() -> httpx.AsyncClient:
    return httpxAsyncClient()


async def get_with_proxy_fallback_on_403(
    client: httpx.AsyncClient,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, Any]] = None,
    timeout: float = 30,
    log_label: str = "",
) -> Optional[Any]:
    """GET `url` via `client` first; on HTTP 403 or 429 (bot challenge / rate limit),
    retry once via curl_cffi with a browser TLS fingerprint before giving up.

    Retry chain:
    1. Direct httpx request.
    2. curl_cffi with `impersonate="chrome124"` - replays a genuine browser TLS
       handshake. Cloudflare-style WAFs (Playtomic, Matchi, ClubSpark) score the
       handshake itself, and httpx's Python-ssl handshake is an automatic fail
       from datacenter IPs such as GitHub Actions runners even when the target
       IP is not blocklisted. Same fix CitySport needed (docs/clubs/citysport.md).

    A 403 or 429 through a direct connection can mean this host's IP is blocklisted or
    rate-limited by Cloudflare / WAF for this specific target.

    Any other non-403/429 HTTP error is raised immediately.

    Returns the successful response (httpx or curl_cffi - both expose .json() /
    .text / .status_code), or `None` if the impersonation retry also failed
    with 403/429.
    """
    try:
        resp = await client.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in (403, 429):
            raise
        last_status = exc.response.status_code

    # Free browser-TLS retry via curl_cffi.
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

    logging.warning(
        f"{log_label}: exhausted direct + TLS-impersonation attempts "
        f"- this run's IP may be blocklisted for this target"
    )
    return None
