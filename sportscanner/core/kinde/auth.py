import asyncio
import hashlib
import time

from sportscanner.logger import logging
from sportscanner.variables import settings
import httpx
from fastapi import HTTPException

# Shared, connection-pooled async client (module-level, never closed - lives
# for the process lifetime), reused instead of a fresh TCP+TLS handshake per
# call.
_client = httpx.AsyncClient()

# Kinde rotates refresh tokens on every use - the old one is invalidated
# immediately (with only a small grace window for retries/parallel requests,
# per Kinde's docs). The frontend sends the same stored refresh token to
# several endpoints at once on page load (/user/, /user/tokens/,
# /notifications/, /user/mcp-connections/), so without coalescing, they race
# to redeem it and all but the winner get invalid_grant (400). A per-token
# lock plus a short-lived cache of the resulting access token means
# concurrent callers share one Kinde exchange instead of racing - Kinde's own
# guidance for this exact scenario is a single-flight mutex keyed per token.
_ACCESS_TOKEN_CACHE_TTL_SECONDS = 45
_access_token_cache: dict[str, tuple[str, float]] = {}
_locks: dict[str, asyncio.Lock] = {}


def _token_hash(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode()).hexdigest()


async def _exchange_refresh_token(refresh_token: str) -> str:
    url = f"{settings.KINDE_DOMAIN}/oauth2/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": settings.KINDE_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # TEMPORARY DIAGNOSTIC - see note above.
    logging.warning(f"[kinde-diag] outgoing payload keys={list(payload.keys())} refresh_token_len={len(payload['refresh_token'])}")

    response = await _client.post(url, data=payload, headers=headers)
    if response.status_code != 200:
        logging.warning(f"[kinde-diag] Kinde token exchange failed: {response.status_code} {response.text}")
        raise HTTPException(status_code=response.status_code, detail=response.json())
    return response.json().get("access_token")


async def get_kinde_access_token(refresh_token: str):
    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "error_description": "Refresh token not provided.",
            },
        )
    # TEMPORARY DIAGNOSTIC (remove once the "more than one refresh token
    # provided" incident is root-caused): logs shape/fingerprint only, never
    # the raw token - checking whether the incoming header already contains
    # multiple bearer/comma-separated values before we ever touch it, which
    # would point at something upstream (proxy/CDN/browser) duplicating the
    # header rather than our own request construction.
    logging.warning(
        f"[kinde-diag] raw Authorization header: len={len(refresh_token)} "
        f"commas={refresh_token.count(',')} bearer_occurrences={refresh_token.lower().count('bearer')} "
        f"prefix={refresh_token[:12]!r} suffix={refresh_token[-6:]!r}"
    )

    if refresh_token.lower().startswith("bearer "):
        refresh_token = refresh_token.split(" ", 1)[1].strip()

    logging.warning(
        f"[kinde-diag] after bearer-strip: len={len(refresh_token)} "
        f"commas={refresh_token.count(',')} prefix={refresh_token[:12]!r} suffix={refresh_token[-6:]!r}"
    )

    token_hash = _token_hash(refresh_token)

    cached = _access_token_cache.get(token_hash)
    if cached and cached[1] > time.monotonic():
        return cached[0]

    lock = _locks.setdefault(token_hash, asyncio.Lock())
    async with lock:
        # Double-checked: another coroutine may have refreshed while we
        # waited for the lock, in which case we just reuse its result
        # instead of spending (rotating away) the refresh token again.
        cached = _access_token_cache.get(token_hash)
        if cached and cached[1] > time.monotonic():
            return cached[0]

        access_token = await _exchange_refresh_token(refresh_token)
        _access_token_cache[token_hash] = (access_token, time.monotonic() + _ACCESS_TOKEN_CACHE_TTL_SECONDS)
        return access_token


async def get_kinde_user_details(access_token: str):
    url = f"{settings.KINDE_DOMAIN}/oauth2/user_profile"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = await _client.get(url, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())
    return response.json()
