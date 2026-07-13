"""
Shared rate limiter, applied selectively to endpoints that touch real money
movement (game joins, Stripe Connect onboarding) rather than site-wide — those
are the routes where unthrottled access has real abuse cost (card-testing
against a live PaymentIntent endpoint, spamming Stripe Express account
creation), not just a performance concern.

Keyed by client IP via slowapi's in-memory store. That's process-local (not
shared across multiple backend replicas) and coarser than per-user limiting,
but it's a meaningful floor against scripted abuse with zero new
infrastructure — revisit with a Redis/Valkey backend (VALKEY_URL is already
configured for caching) if this ever needs to hold across replicas.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
