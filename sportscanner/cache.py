"""Thin best-effort cache wrapper around Valkey (Redis-protocol-compatible).

Caching is optional and must never break a request: if VALKEY_URL isn't
configured, or the cache is unreachable, every function here degrades to a
silent no-op (cache miss) so callers always fall through to the real data
source. TTL is short (see settings.CACHE_TTL_SECONDS) because the cached data
(postcode geocoding, venues-within-radius) is near-static but not immutable —
new venues can be added at any time.
"""
import json
from typing import Any, Optional

from sportscanner.logger import logging
from sportscanner.variables import settings

_client = None
_client_init_attempted = False


def _get_client():
    """Lazily create a single Valkey client for the process. Returns None if
    unconfigured or unreachable — callers must treat that as a cache miss."""
    global _client, _client_init_attempted
    if _client_init_attempted:
        return _client
    _client_init_attempted = True

    if not settings.VALKEY_URL:
        logging.debug("VALKEY_URL not configured — caching disabled")
        return None

    try:
        import redis
        _client = redis.from_url(
            settings.VALKEY_URL,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=True,
        )
        _client.ping()
        logging.info("Connected to Valkey cache")
    except Exception as e:
        logging.warning(f"Valkey cache unavailable, continuing without caching: {e}")
        _client = None
    return _client


def cache_get_json(key: str) -> Optional[Any]:
    """Returns the cached value for `key`, or None on a miss/any cache failure.

    Logs an explicit HIT/MISS at INFO so cache behaviour is directly visible in
    logs instead of having to be inferred from request timing (which stops being
    a reliable signal once the cache is warm and everything is already fast).
    """
    client = _get_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if raw is not None:
            logging.info(f"Cache HIT: {key}")
            return json.loads(raw)
        logging.info(f"Cache MISS: {key}")
        return None
    except Exception as e:
        logging.warning(f"Cache GET failed for key={key}: {e}")
        return None


def cache_set_json(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    """Best-effort cache write. Never raises — a failed write just means no caching."""
    client = _get_client()
    if client is None:
        return
    try:
        ttl = ttl_seconds or settings.CACHE_TTL_SECONDS
        client.set(key, json.dumps(value), ex=ttl)
        logging.info(f"Cache SET: {key} (ttl={ttl}s)")
    except Exception as e:
        logging.warning(f"Cache SET failed for key={key}: {e}")
