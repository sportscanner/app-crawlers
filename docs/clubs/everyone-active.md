# Everyone Active

12 venues, `https://www.everyoneactive.com/`. Badminton.
Code: `sportscanner/crawlers/parsers/everyoneactive/`.

## API shape

Per-venue hardcoded `activityId` strings (e.g. `queen-mother-sports-centre` ->
`"155BADMINTON1"`, `reynolds-sports-centre` -> `"119BADM050SH001"`) in a dict
literal in `EveryoneActiveBadmintonRequestStrategy.generate_request_details`.
These IDs don't follow a predictable pattern across venues (different
prefixes/suffixes per centre), so there's no slug-derivation logic to maintain —
each new venue just needs its ID looked up once and added to the dict, the same
pattern as Matchi's `SLUG_TO_FACILITY_ID` and Playtomic's `SLUG_TO_TENANT_ID`.

Dates are passed as UTC timestamp ranges (`get_utc_timestamps(fetch_date)` in
`everyoneactive/core/utils.py`), not a plain date string like the Gladstone-family
providers use.

## Fixed July 2026: blocked from GitHub Actions specifically, not locally

`caching.everyoneactive.com` (note the "caching" subdomain — this is a CDN/WAF
layer in front of the real API, not the origin directly) silently blocked every
single request that came from the production GitHub Actions runner IP range,
consistently, on every scheduled run (`0/120 requests returned data`, checked
across 7+ consecutive runs — not intermittent). The same request, run from a
residential/dev machine or through the existing rotating proxy, returns real
data immediately. No header, User-Agent, or request-shape change fixed this: it
isn't a hard error to react to (no 4xx/5xx, no connection error) — the response
is a normal `200` with valid JSON, just silently empty (`bookableItems: []` in
effect), which is indistinguishable in the logs from "this venue genuinely has
no slots right now" unless you already know to suspect it. This is very likely
IP/ASN-based blocking of GitHub's well-known hosted-runner ranges (a common WAF
rule, since those ranges are heavily used for scraping across the internet).

Fixed by overriding `BaseCrawler._http_client()` in `EveryoneActiveCrawler` to
route through the existing rotating proxy
(`httpxAsyncClientWithProxyRotation()`) instead of flipping the global
`USE_PROXIES` setting for every provider — every other provider works fine
directly, so there's no reason to route them all through a proxy just to fix
this one.

This also surfaced a real, unrelated latent bug: `httpxAsyncClientWithProxyRotation()`
itself was broken (`TypeError: AsyncClient.__init__() got an unexpected keyword
argument 'proxies'`) — it used the per-scheme `proxies={"http://": ..., "https://":
...}` dict mapping that httpx 0.28 removed in favour of a single `proxy=` string.
This had been silently dead code since `USE_PROXIES` has always defaulted to
`False`, so nothing had exercised this function until this fix used it for the
first time. Fixed in `crawlers/anonymize/proxies.py`.

If another provider ever needs the same treatment (works locally, fails only
from CI), override `_http_client()` on that provider's crawler the same way
rather than touching the global setting.

## Status (July 2026)

Confirmed live through the real `coroutines()` entry point: 8/12 venues
returned data on a short probe window (the other 4 having zero slots on the
specific dates checked is consistent with genuine no-availability elsewhere in
the roster, not a failure).

## Adding a new venue

Look up the venue's `activityId` from the network tab on
`everyoneactive.com`'s own booking flow for that centre, then add
`"venue-slug": "theActivityId"` to the dict. There's no discovery API for this
one (unlike Better/GLL's `/categories` endpoint) — it has to be read off the live
site.
