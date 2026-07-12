# Playtomic

33 venues, `https://playtomic.com`. Padel.
Code: `sportscanner/crawlers/parsers/playtomic/`.

## API shape

Base: `GET https://playtomic.com/api/clubs/availability?tenant_id={uuid}&date=YYYY-MM-DD&sport_id=PADEL`

`tenant_id` is a stable UUID assigned once when a club registers on Playtomic and
never changes, hardcoded in `SLUG_TO_TENANT_ID` (`playtomic/core/strategy.py`).
To find a new venue's `tenant_id`: `api.playtomic.io/v1/tenants` (or read it off
the club's page network requests).

Response is a flat JSON array of per-court resources, aggregated by
`(start_time, duration)` across courts in `_resources_to_unified()` — `spaces`
reflects how many courts are bookable at that exact slot, not a single
court's availability.

Booking URLs need a separate slug: the API's `tenant_id`/slug (stored as
`venue.slug` in `venues.json`) doesn't always match the public website URL —
some tenant slugs have trailing dashes or triple-dash sequences that don't
appear on `playtomic.com/clubs/{slug}`. `_BOOKING_SLUG_OVERRIDES` maps the API
slug to the correct public slug; a value of `None` means no working public page
exists for that venue at all.

**This provider does not use `BaseCrawler`'s per-venue request loop.** Like
Matchi, Playtomic's availability API is queried by `tenant_id` param rather than
a per-venue URL path, so `PlaytomicPadelCrawler` overrides `ScraperCoroutines`
directly and drives `PlaytomicAvailabilityFetcher.fetch_venue_date()` itself.

## Fixed July 2026: same unbounded-concurrency bug as Matchi

Discovered while investigating why a handful of venues (Powerleague Mill Hill,
S3 Padel Brent Cross, Boxx Padel, Catford Padel Collective, Padel Tree
Brentford) intermittently 403'd in production logs despite each responding
cleanly (`200`, correct empty-or-populated array) when curled in isolation.

Root cause: exactly the same structural bug just fixed in Matchi (see
[matchi.md](matchi.md)) — bypassing `BaseCrawler` means bypassing its semaphore
too. `_crawl_async` fired every `(venue, date)` request in one unbounded
`asyncio.gather` — with 33 venues × up to 10 dates, that's 300+ simultaneous
requests in a single burst. Playtomic's WAF was rate-limiting a random-looking
subset of that burst per run, which read as "these specific venues are broken"
when it was actually "whichever requests happened to land during the throttled
window get 403'd, and that varies by run."

Playtomic already had proper browser headers (`_HEADERS` in
`playtomic/core/strategy.py`), which is likely why this manifested as a handful
of intermittent failures rather than the total, every-request outage Matchi hit
(Matchi had neither headers nor a concurrency cap).

Fixed the same way as Matchi: `fetch_venue_date()` now takes an
`asyncio.Semaphore` (sized to `CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER`,
same as every other provider) and wraps the actual `client.get()` call in it,
threaded down from `_crawl_async`.

If specific Playtomic venues start 403ing intermittently again, check for a
regression here (unbounded concurrency creeping back in) before assuming those
specific venues are the problem — the venue identity of which requests fail is
a symptom of burst timing, not evidence about that venue.

## Status (July 2026)

Confirmed live: 29 of 33 venues returned data in the probe window; the other 4
returned clean `200` responses with genuinely empty availability (not errors) —
re-verified directly with `curl` across a week of dates. Not a bug.
