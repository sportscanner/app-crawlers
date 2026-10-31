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

import asyncio
import os
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

import httpx

from sportscanner.logger import logging

_PRE_TAG_PATTERN = re.compile(r"<pre[^>]*>(.*)</pre>", re.DOTALL)

# Only these hosts are worth the browser round-trip by default.
_FLARESOLVERR_DEFAULT_HOSTS = ("clubspark.lta.org.uk",)


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


def _solve_sync(url: str, max_timeout_ms: int, log_label: str) -> Optional[Dict[str, Any]]:
    """Synchronous FlareSolverr POST, for call sites that aren't async (e.g.
    mytimeactive's get_anonymous_jwt(), called at crawler construction time
    before any event loop exists). Returns the raw `solution` dict, or None."""
    endpoint = os.environ.get("FLARESOLVERR_URL")
    if not endpoint:
        return None
    try:
        with httpx.Client(timeout=(max_timeout_ms / 1000) + 10) as client:
            resp = client.post(
                endpoint,
                json={"cmd": "request.get", "url": url, "maxTimeout": max_timeout_ms},
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logging.debug(f"{log_label}: FlareSolverr request failed: {type(exc).__name__}: {exc!r}")
        return None
    if payload.get("status") != "ok":
        logging.debug(f"{log_label}: FlareSolverr did not solve the challenge: {payload.get('message')}")
        return None
    return payload.get("solution") or {}


def get_cookie_via_flaresolverr(
    url: str, cookie_name: str, max_timeout_ms: int = 60_000, log_label: str = ""
) -> Optional[str]:
    """Solves `url` through FlareSolverr and returns one cookie's value from the
    resulting browser session, or None (including when FLARESOLVERR_URL isn't
    set - a true no-op). For endpoints whose whole purpose is to *set* a
    session cookie (e.g. mytimeactive's anonymous-JWT endpoint) rather than
    return a JSON body."""
    solution = _solve_sync(url, max_timeout_ms, log_label)
    if not solution:
        return None
    for cookie in solution.get("cookies", []):
        if cookie.get("name") == cookie_name:
            return cookie.get("value")
    logging.debug(f"{log_label}: FlareSolverr session had no '{cookie_name}' cookie")
    return None


async def get_via_flaresolverr(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    max_timeout_ms: int = 60_000,
    log_label: str = "",
) -> Optional[FlareSolverrResponse]:
    """Solve `url` (+ `params`) through a FlareSolverr sidecar, if configured.

    Returns None immediately (no network call at all) when `FLARESOLVERR_URL`
    isn't set, so this is safe to call unconditionally from any retry chain.

    A single browser session is reused for the lifetime of the process (up to
    `_SESSION_TTL_SECONDS`). Creating a browser per call costs ~11 s; reusing
    one brings subsequent venues down to well under a second. Requests are
    serialised because one FlareSolverr session drives one browser tab.

    Headers can't be forwarded - FlareSolverr drives a real browser tab, not a
    raw HTTP request, so only the URL reaches the target; a `referer` some
    providers require must already be encoded in the URL/cookies if needed.
    """
    endpoint = os.environ.get("FLARESOLVERR_URL")
    if not endpoint:
        return None

    # The solver is slow (it drives a browser) and cannot fix a CloudFront
    # range-ban, so only invoke it for the hosts that actually benefit. This
    # keeps a global FLARESOLVERR_URL from adding seconds to every Playtomic or
    # Matchi 403. Override with FLARESOLVERR_HOSTS=a.com,b.com if that changes.
    hosts_env = os.environ.get("FLARESOLVERR_HOSTS")
    allowed_hosts = (
        tuple(h.strip().lower() for h in hosts_env.split(",") if h.strip())
        if hosts_env is not None
        else _FLARESOLVERR_DEFAULT_HOSTS
    )
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed_hosts:
        return None

    global _session_id, _session_created_at, _request_lock

    if _request_lock is None:
        _request_lock = asyncio.Lock()

    full_url = f"{url}?{urlencode(params)}" if params else url
    timeout = (max_timeout_ms / 1000) + 10

    async with _request_lock:
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    session = _session_id
                    if session is None or (time.time() - _session_created_at) > _SESSION_TTL_SECONDS:
                        session = await _create_session(client, endpoint, log_label)

                    resp = await client.post(
                        endpoint,
                        json={
                            "cmd": "request.get",
                            "url": full_url,
                            "maxTimeout": max_timeout_ms,
                            "session": session,
                            "session_ttl_minutes": _SESSION_TTL_SECONDS // 60,
                        },
                    )
                    resp.raise_for_status()
                    payload = resp.json()
            except Exception as exc:
                logging.debug(
                    f"{log_label}: FlareSolverr request failed: {type(exc).__name__}: {exc!r}"
                )
                await _drop_session(endpoint, log_label)
                return None

            if payload.get("status") == "ok":
                solution = payload.get("solution") or {}
                status_code = solution.get("status", 200)
                body = _extract_body(solution.get("response", ""))
                logging.debug(
                    f"{log_label}: FlareSolverr solved (status {status_code}, "
                    f"{len(body)} bytes, session reuse attempt {attempt})"
                )
                return FlareSolverrResponse(status_code=status_code, text=body)

            logging.debug(
                f"{log_label}: FlareSolverr did not solve the challenge "
                f"(attempt {attempt}): {payload.get('message')}"
            )
            # The session may be stale or the challenge failed. Drop it so the
            # retry gets a fresh browser.
            await _drop_session(endpoint, log_label)

    return None


_SESSION_TTL_SECONDS = 20 * 60
_session_id: Optional[str] = None
_session_created_at: float = 0.0
_request_lock: Optional[asyncio.Lock] = None


async def _create_session(client: httpx.AsyncClient, endpoint: str, log_label: str) -> str:
    """Create the shared browser session, replacing any previous one."""
    global _session_id, _session_created_at

    if _session_id:
        await _destroy_session(client, endpoint, _session_id)

    resp = await client.post(endpoint, json={"cmd": "sessions.create"})
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "ok" or not payload.get("session"):
        raise RuntimeError(f"FlareSolverr could not create a session: {payload.get('message')}")

    _session_id = payload["session"]
    _session_created_at = time.time()
    logging.debug(f"{log_label}: FlareSolverr session created ({_session_id})")
    return _session_id


async def _destroy_session(client: httpx.AsyncClient, endpoint: str, session: str) -> None:
    try:
        await client.post(endpoint, json={"cmd": "sessions.destroy", "session": session})
    except Exception:
        pass


async def _drop_session(endpoint: str, log_label: str) -> None:
    """Forget the cached session and ask FlareSolverr to tear it down."""
    global _session_id, _session_created_at

    session, _session_id, _session_created_at = _session_id, None, 0.0
    if not session:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await _destroy_session(client, endpoint, session)
        logging.debug(f"{log_label}: FlareSolverr session dropped ({session})")
    except Exception:
        pass
