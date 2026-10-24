# Everyone Active

15 venues (12 badminton, 6 squash, 3 offering both), `https://www.everyoneactive.com/`. Badminton and Squash.
Code: `sportscanner/crawlers/parsers/everyoneactive/`.

## API shape

Per-venue hardcoded `activityId` strings in dict literals:
- Badminton: `EveryoneActiveBadmintonRequestStrategy.generate_request_details`
- Squash: `EveryoneActiveSquashRequestStrategy.generate_request_details`

Dates are passed as UTC timestamp ranges (`get_utc_timestamps(fetch_date)` in `everyoneactive/core/utils.py`), not a plain date string.

Endpoints:
- Availability: `GET https://caching.everyoneactive.com/aws/api/activity/availability?toUTC={to_utc}&activityId={activityId}&fromUTC={from_utc}&locale=en_GB`
- Activity discovery: `GET https://caching.everyoneactive.com/aws/api/activity/list`
- Header for both: `AuthenticationKey: M0bi1eProB00king$`

The discovery endpoint returns all activity types across all centres in a single JSON payload (`types[].sites[].acts[]`). Filter by activity name (such as "Squash 45 Min") and site name to retrieve the `activityId` and duration for any venue.

## Squash Activity Identifiers

Squash sessions run for 45 minutes. The availability response does not include pricing, so slots are stamped with `price="N/A"`.

Verified London squash venues and activity codes:

| Venue | slug | activityId | Courts |
|---|---|---|---|
| Queen Mother Sports Centre | `queen-mother-sports-centre` | `155SQUASH` | 3 |
| Porchester Centre | `porchester-centre` | `153SQUASH` | 1 |
| Harrow Leisure Centre | `harrow-leisure-centre` | `097SQUA050SC001` | 6 |
| Cheam Leisure Centre | `cheam-leisure-centre` | `073SQUASH02` | 1 |
| Vale Farm Sports Centre | `vale-farm-sports-centre` | `101SQUA050SC001` | 2 |
| Westway Sports & Fitness Centre | `westway-sports-fitness-centre` | `163SQUASH` | 2 |

## Badminton Activity Identifiers

| Venue | slug | activityId |
|---|---|---|
| Queen Mother Sports Centre | `queen-mother-sports-centre` | `155BADMINTON1` |
| St Augustine's Sports Centre | `st-augustines-sports-centre` | `156BADMINTON1` |
| Reynolds Sports Centre | `reynolds-sports-centre` | `119BADM050SH001` |
| Moberly Sports Centre | `moberly-sports-centre` | `160BADM055SH001` |
| Little Venice Sports Centre | `little-venice-sports-centre` | `158BADMINTON1` |
| Jubilee Community Leisure Centre | `jubilee-community-leisure-centre` | `282BADM060SH001` |
| Church Street Community Leisure Centre | `church-street-community-leisure-centre` | `270BADM060SH001` |
| Academy Sport | `academy-sport` | `262BADM060SH001` |
| Vale Farm Sports Centre | `vale-farm-sports-centre` | `101BADMINTON1` |
| Greenford Sports Centre | `greenford-sports-centre` | `118BADM050SH001` |
| Harrow Leisure Centre | `harrow-leisure-centre` | `091BADMINT001` |
| The Centre (Slough) | `the-centre-slough` | `208BADM060SH001` |

## WAF: total outage from GitHub Actions (September 2026)

`caching.everyoneactive.com` sits behind Cloudflare (`server: cloudflare`, confirmed via a live header check) and blocks 100% of requests from GitHub Actions runner IPs — residential/local IP connections succeed directly. Confirmed live via full CI logs (2026-09-14): **all 120 badminton requests in a run (12 venues × ~10 dates) exhausted every retry stage and got 403 every single time.** This is not new; the same 100% failure rate was already true before the fingerprint-rotation change below.

The paid rotating-proxy pool that used to sit in front of this was removed in August 2026 (see `anonymize/proxies.py`) — its exits were blocklisted by the same WAF as the runner range, so it was burning budget for no benefit. `EveryoneActiveCrawler._fetch_with_retry` now retries entirely through `curl_cffi`, cycling through `next_impersonate_profile()`'s rotation (`chrome136`, `safari180`, `firefox135`, `chrome124`) on each of its up to 5 attempts per request, replacing what used to be a plain-httpx retry with no fingerprint at all (which had no chance of getting past a WAF that already scored the handshake). **This is a real improvement in principle but made no measurable difference here** — every request still fails, same as before the change. Combined with the identical result for ClubSpark and mytimeactive (same Cloudflare WAF, same GitHub Actions IP range - see `clubspark.md`, `mytime-active.md`), including a live FlareSolverr (real headless browser) test that also made no difference for ClubSpark, the working theory is that this specific IP range is scored badly enough that no client-side technique (TLS fingerprint or real JS execution) gets past it. The only fix that would plausibly work is a non-datacenter egress IP for these three providers specifically (residential proxy, or a self-hosted runner) - a cost/infra decision, not a code fix.

## Status (August 2026, superseded)

Verified live:
- Badminton: 12 venues verified.
- Squash: 6 London venues verified (155 slots returned across 6 centres on test date, genuine mixed availability).

This was true from a residential IP at the time. As of September 2026 it does not reflect production (GitHub Actions) behavior - see "WAF: total outage from GitHub Actions" above.
