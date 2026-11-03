"""Thin best-effort cache wrapper around Valkey (Redis-protocol-compatible).

Caching is optional and must never break a request: if VALKEY_URL isn't
configured, or the cache is unreachable, every function here degrades to a
silent no-op (cache miss) so callers always fall through to the real data
source. TTL is short (see settings.CACHE_TTL_SECONDS) because the cached data
(postcode geocoding, venues-within-radius) is near-static but not immutable —
new venues can be added at any time.
"""
import json
import threading
import time
from typing import Any, Callable, Optional

from sportscanner.logger import logging
from sportscanner.variables import settings

_client = None
_client_init_attempted = False

# VALKEY_URL points at a shared instance (other apps use it too), so every
# key we touch is namespaced to avoid colliding with theirs.
KEY_PREFIX = "sportscanner:"

# Process-local tier in front of Valkey. A search request used to pay a Redis
# round trip (plus, on a miss, a cross-region Postgres round trip) for data that
# is identical on every request: the venue lookup table and the set of social
# game venues. Those two are hit on the hot path, so they are memoised in the
# worker process as well. Small, bounded, and short-lived on purpose: with a
# single uvicorn worker this is one copy, and it can never outlive the Valkey
# TTL for the same key.
_local_store: dict[str, tuple[float, Any]] = {}
_local_lock = threading.Lock()
_LOCAL_MAX_ENTRIES = 256


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
        raw = client.get(KEY_PREFIX + key)
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
        client.set(KEY_PREFIX + key, json.dumps(value), ex=ttl)
        logging.info(f"Cache SET: {key} (ttl={ttl}s)")
    except Exception as e:
        logging.warning(f"Cache SET failed for key={key}: {e}")


def _local_get(key: str) -> Optional[Any]:
    entry = _local_store.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() >= expires_at:
        return None
    return value


def _local_set(key: str, value: Any, ttl_seconds: int) -> None:
    with _local_lock:
        if key not in _local_store and len(_local_store) >= _LOCAL_MAX_ENTRIES:
            # Cheap bound: drop everything rather than track LRU order. These
            # entries are rebuildable from Postgres/Valkey, so a flush is safe.
            _local_store.clear()
        _local_store[key] = (time.monotonic() + ttl_seconds, value)


def clear_local_cache() -> None:
    """Drop the process-local tier. Used by tests and after venue changes."""
    with _local_lock:
        _local_store.clear()


def get_or_load_json(
    key: str,
    loader: Callable[[], Any],
    ttl_seconds: Optional[int] = None,
) -> Any:
    """Return `key` from the process-local tier, then Valkey, then `loader()`.

    Both tiers are populated on a miss so the next request skips the database.
    The loader still runs whenever the cache is unavailable, which keeps the
    existing "caching is optional" guarantee.
    """
    ttl = ttl_seconds or settings.CACHE_TTL_SECONDS

    local = _local_get(key)
    if local is not None:
        return local

    cached = cache_get_json(key)
    if cached is not None:
        _local_set(key, cached, ttl)
        return cached

    value = loader()
    _local_set(key, value, ttl)
    cache_set_json(key, value, ttl_seconds=ttl)
    return value
