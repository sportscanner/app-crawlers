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
layer in front of the real API, not the origin directly) blocked every request
from the production GitHub Actions runner IP, consistently, on every scheduled
run (`0/120 requests returned data`, checked across 7+ consecutive runs — not
intermittent). The same request from a residential/dev machine returns real
data immediately. This is IP/ASN-based blocking of GitHub's well-known
hosted-runner ranges (a common WAF rule, since those ranges are heavily used
for scraping across the internet) — no header or request-shape change could
have fixed it.

**First attempt (routing through the existing rotating proxy via a
`BaseCrawler._http_client()` hook) only partially worked — 47/120 (39%) — and
that's worth understanding, not just patching over.** The proxy account
(`ROTATING_PROXY_ENDPOINT`, Webshare) is a free-tier plan: "No Automatic Proxy
List Refreshes," meaning it isn't actually a large, fresh rotating pool — it's
a small, static set of exit IPs (confirmed empirically: 4 distinct IPs seen
across 8 requests), some fraction of which are *already* blocklisted by this
site's WAF and will never rotate out on this plan. Repeating the identical
request against the real endpoint got an HTTP 403 (blocklisted pool IP)
roughly 55-65% of the time and a clean 200 the rest, both in isolated testing
and matching production's 39% first-try success rate almost exactly. The
`_http_client()` hook approach was reverted (see git history) since it doesn't
fit this problem: a plain client swap doesn't help when the *pool itself* is
partly bad, no matter which client uses it.

**Actual fix: retry with a brand-new proxied connection on 403.** Since each
fresh connection is a fresh shot at Webshare's small pool (confirmed: repeated
standalone requests, each a new connection, land on different exit IPs), an
HTTP 403 through this proxy doesn't mean "venue doesn't offer this activity"
the way a 4xx means for every other provider — it means "you drew a
blocklisted pool IP, try again." `EveryoneActiveCrawler` bypasses
`BaseCrawler`'s shared fetch loop (like Matchi/Playtomic/CitySport) and opens a
new `httpxAsyncClientWithProxyRotation()` client per attempt, up to 5 attempts
per request, before giving up. At a ~60% failure rate per attempt, 5 attempts
brings the chance of a request failing outright down to roughly
0.6⁵ ≈ 8%, and confirmed live: 12/12 venues returned data, 1250 slots, ~10s for
120 requests (a handful of individual (venue, date) requests still exhaust all
5 attempts on bad luck — expected, not a bug).

Retrying against a *shared, reused* connection would not have worked — Webshare's
rotation happens at connection/tunnel setup, not per-request within one
kept-alive connection, which is why each retry opens a genuinely new client
rather than reusing one across attempts.

This also surfaced a real, unrelated latent bug: `httpxAsyncClientWithProxyRotation()`
itself was broken (`TypeError: AsyncClient.__init__() got an unexpected keyword
argument 'proxies'`) — it used the per-scheme `proxies={"http://": ..., "https://":
...}` dict mapping that httpx 0.28 removed in favour of a single `proxy=` string.
This had been silently dead code since `USE_PROXIES` has always defaulted to
`False`, so nothing had exercised this function until this fix used it for the
first time. Fixed in `crawlers/anonymize/proxies.py`.

If the Webshare plan ever gets upgraded/refreshed (a paid plan with automatic
list refreshes, or a different provider entirely), the retry count could
likely come down from 5, but there's no harm in leaving it as-is — successful
attempts return immediately, the extra retry budget only gets used when needed.

## Status (July 2026)

Fixed and confirmed live through the real `coroutines()` entry point: 12/12
venues returned data (1250 slots, ~10s for a 10-day/12-venue crawl). If this
regresses, check the proxy account's plan details first (Webshare dashboard)
before assuming a code change broke it — a further-degraded free-tier pool
would show up as more frequent "exhausted N attempts" warnings.

## Adding a new venue

Look up the venue's `activityId` from the network tab on
`everyoneactive.com`'s own booking flow for that centre, then add
`"venue-slug": "theActivityId"` to the dict. There's no discovery API for this
one (unlike Better/GLL's `/categories` endpoint) — it has to be read off the live
site.
