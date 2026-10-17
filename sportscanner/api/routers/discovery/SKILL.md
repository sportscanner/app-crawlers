---
name: find-london-courts
description: Find badminton, squash, pickleball, padel and tennis court availability and provider booking links in London using SportScanner's public API.
---

# Find London courts

Use this skill when a user wants available London sports courts, prices or booking links. No account or credentials are needed for REST search.

1. Read https://api.sportscanner.co.uk/agents.md for the current contract. Ask the user for missing sport, UK postcode or date. Resolve relative dates in Europe/London.
2. POST `https://api.sportscanner.co.uk/search/{sport}?date=YYYY-MM-DD` with JSON containing `postcode`, `timeRange` (`starting`/`ending` in HH:MM), `radius` in miles, `sortBy` (`distance` or `price`), `analytics` (`consecutiveSlots: null`, `searchUserPreferredLocations: false`, `specifiedVenues: null`), and `indoor: null` unless specified.
3. Compare individual slot prices (GBP), local times, venue distance and `last_refreshed`. Flag `healthcheck: deprecated` data as stale. Return provider `bookingUrl` links. An empty result means no matching slots in current coverage.
4. For social games use `GET /games?sport=pickleball&date=YYYY-MM-DD`; these are per-person sessions rather than whole-court bookings.

SportScanner cannot reserve or pay for a court. Do not claim that a search confirms a booking. Provider booking may require the user's login. Never invent availability, URLs or prices, and never bypass provider authentication. Correct 400/422 errors; use bounded backoff for temporary failures. Do not bulk poll.
