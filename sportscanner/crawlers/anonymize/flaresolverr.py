"""Optional last-resort WAF bypass via a FlareSolverr sidecar.

ClubSpark (and possibly other Cloudflare-fronted providers) sometimes 403s
every request from a given GitHub Actions run even after TLS-impersonation
retries are exhausted. Confirmed live (2026-09) against a real always-blocked
ClubSpark venue: the response we get back is a genuine solvable Cloudflare
challenge (a real browser gets issued a `cf_clearance` cookie after solving
it), not a network-level "Access Denied" - so a headless-browser stage that
actually executes Cloudflare's JS challenge can plausibly succeed even where
curl_cffi's TLS-fingerprint-only impersonation cannot.

This module is a true no-op unless `FLARESOLVERR_URL` is set (e.g.
`http://localhost:8191/v1`, when a `flaresolverr/flaresolverr` container is
running alongside the crawler with `--network=host`). No env var, no import
cost paid at call time beyond checking `os.environ` - existing behaviour for
every provider/environment that doesn't opt in is completely unchanged.
"""

import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from sportscanner.logger import logging

_PRE_TAG_PATTERN = re.compile(r"<pre[^>]*>(.*)</pre>", re.DOTALL)


class FlareSolverrResponse:
    """Minimal httpx.Response-compatible wrapper around a solved FlareSolverr result."""

    def __init__(self, status_code: int, text: str, headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {"content-type": "application/json"}

    def json(self) -> Any:
        import json

        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"FlareSolverr solved response returned status {self.status_code}",
                request=None,  # type: ignore[arg-type]
                response=None,  # type: ignore[arg-type]
            )


def _extract_body(raw_html: str) -> str:
    """FlareSolverr returns the full page source, not the raw response body.

    For a JSON API endpoint, a real browser wraps the response in
    `<html><body><pre>{...json...}</pre></body></html>` - confirmed live
    against ClubSpark's GetVenueSessions endpoint. Fall back to the raw text
    unchanged if it isn't wrapped (e.g. FlareSolverr version differences).
    """
    match = _PRE_TAG_PATTERN.search(raw_html)
    if match:
        return match.group(1)
    return raw_html


async def get_via_flaresolverr(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    max_timeout_ms: int = 60_000,
    log_label: str = "",
) -> Optional[FlareSolverrResponse]:
    """Solve `url` (+ `params`) through a FlareSolverr sidecar, if configured.

    Returns None immediately (no network call at all) when `FLARESOLVERR_URL`
    isn't set, so this is safe to call unconditionally from any retry chain.
    Headers can't be forwarded - FlareSolverr drives a real browser tab, not a
    raw HTTP request, so only the URL reaches the target; a `referer` some
    providers require must already be encoded in the URL/cookies if needed.
    """
    endpoint = os.environ.get("FLARESOLVERR_URL")
    if not endpoint:
        return None

    full_url = f"{url}?{urlencode(params)}" if params else url

    try:
        async with httpx.AsyncClient(timeout=(max_timeout_ms / 1000) + 10) as client:
            resp = await client.post(
                endpoint,
                json={
                    "cmd": "request.get",
                    "url": full_url,
                    "maxTimeout": max_timeout_ms,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logging.debug(f"{log_label}: FlareSolverr request failed: {type(exc).__name__}: {exc!r}")
        return None

    if payload.get("status") != "ok":
        logging.debug(f"{log_label}: FlareSolverr did not solve the challenge: {payload.get('message')}")
        return None

    solution = payload.get("solution") or {}
    status_code = solution.get("status", 200)
    body = _extract_body(solution.get("response", ""))
    logging.debug(f"{log_label}: FlareSolverr solved (status {status_code}, {len(body)} bytes)")
    return FlareSolverrResponse(status_code=status_code, text=body)
