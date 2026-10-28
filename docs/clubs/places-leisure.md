# Places Leisure

8 venues, `https://www.placesleisure.org`. Badminton (8 venues), pickleball (6 venues). No padel found anywhere in the operator's estate.
Code: `sportscanner/crawlers/parsers/placesleisure/`.
Added July 2026.

## API shape: two-phase, unlike every other provider

Places Leisure runs on the same Gladstone booking engine as Better/GLL and
Tower Hamlets (`placesleisure.gladstonego.cloud`), but that domain 401s on
anonymous requests, same auth wall as Tower Hamlets. Unlike Tower Hamlets,
there's no need for the Playwright/JWT dance here: `placesleisure.org`
(Umbraco CMS) proxies a public, anonymous subset of the same booking data
through its own API, used by the site's own timetable widget. No auth needed
anywhere in this flow, confirmed live.

**Phase 1: schedule discovery.** `GET https://www.placesleisure.org/centres/{slug}/`
embeds several weeks of schedule *structure* (which slots exist, when) as
HTML-entity-escaped JSON directly in the page source:
```
{"s":"2026-07-13T07:30:00Z","e":"2026-07-13T08:29:59Z","aId":"231A000101","al":"MultipleLocation_...","ag":"BADMINTON"}
```
`html.unescape()` the raw HTML, then regex for `"ag":"BADMINTON"` or
`"ag":"PICKLEBALL"` entries. This is schedule only, no live availability.

**Phase 2: per-slot availability.** `GET /umbraco/api/timetables/getavailability?activityId=...&siteId=...&locationId=...&startDate=...`
once per unique `(activityId, locationId, startDate)` triple from phase 1,
returns real per-court status:
```json
{"data":[{"locationId":"231ZCRT001","locationName":"Court 1","status":"Available", ...}, ...],"success":true}
```
`spaces` in `UnifiedParserSchema` is the count of courts with
`status == "Available"` out of however many the response lists.

One HTML fetch per venue (cheap) followed by potentially hundreds of
availability calls per venue (confirmed: 240-627 unique badminton slot
combinations per venue across the schedule window) - comparable in request
volume to Better/GLL, handled the same way via the existing per-provider
concurrency semaphore.

## Why this bypasses BaseCrawler's standard loop

Same reasoning as Matchi/Playtomic/CitySport: the standard
`AbstractRequestStrategy.generate_request_details()` shape is one request (or
a fixed few) per `(venue, date)`. This provider needs a fundamentally
different shape (one schedule fetch per venue regardless of date count, then
a variable number of availability calls derived from what that schedule
contains) that doesn't fit the per-venue-per-date contract at all.
`PlacesLeisureBadmintonCrawler`/`PlacesLeisurePickleballCrawler` both
override `ScraperCoroutines` directly; the shared fetch logic lives in
`core/strategy.py`'s `PlacesLeisureSlotFetcher`, parametrized by sport
(`activity_group` for the schedule filter, `category` for the output schema)
so badminton and pickleball don't duplicate the two-phase fetch code.

## Activity IDs are not hardcoded

Unlike Matchi's `SLUG_TO_FACILITY_ID` or Playtomic's `SLUG_TO_TENANT_ID`,
`core/venues.py` only hardcodes `siteId` per venue (read off the
`<input id="site-id" value="...">` element on each centre's page). Activity
IDs are discovered fresh from the schedule on every crawl instead, because
they don't follow a derivable pattern and some venues expose several for the
same sport (confirmed: Tolworth has 4 separate badminton activity IDs,
Malden has 2). Hardcoding them would risk silently going stale; parsing them
fresh costs nothing extra since phase 1 already has to run per venue anyway.

## No price data available anonymously

Checked three places: the centre page (only shows monthly membership
pricing, not pay-as-you-go court hire), the availability response (no price
field), and the Gladstone booking deep-link (`placesleisure.gladstonego.cloud/book/details`,
renders as an near-empty stub without an authenticated session). No real
per-centre price is obtainable, so `price` is a hardcoded
`"£12.00"` London leisure-centre figure (see the comment in
`core/strategy.py`), not a scraped value. Revisit if a pricing source turns up.

## Venues confirmed live (July 2026)

Facility tags on the centre-search API (`/umbraco/api/centre/search`) proved
unreliable for finding badminton/pickleball (several venues with real
badminton/pickleball had empty or unrelated facility tags) - venues were
confirmed by checking each candidate centre page directly for
`"ag":"BADMINTON"` / `"ag":"PICKLEBALL"` schedule entries.

| Venue | Borough | siteId | Badminton | Pickleball |
|---|---|---|---|---|
| Chessington Sports Centre | Kingston upon Thames | 231 | yes | no |
| Battersea Sports Centre | Wandsworth | 229 | yes | yes |
| Roehampton Sports and Fitness Centre | Wandsworth | 18 | yes | yes |
| Latchmere Leisure Centre | Wandsworth | 13 | yes | yes |
| Malden Centre | Kingston upon Thames | 98 | yes | no |
| Tolworth Recreation Centre | Kingston upon Thames | 33 | yes | yes |
| Tooting Leisure Centre | Wandsworth | 15 | yes | yes |
| Wandle Recreation Centre | Wandsworth | 16 | yes | yes |

Also found (not implemented, outside this platform's badminton/pickleball/padel
scope): Balham Leisure Centre and Tolworth Recreation Centre offer squash.

Places Leisure has no venues at all in Richmond upon Thames, Hounslow,
Sutton, Lewisham, or Bromley - checked the full centre list
(`/umbraco/api/centre/search`), this operator simply doesn't have a presence
in those boroughs. Wandsworth and Kingston upon Thames are well covered by
this one addition, the others aren't solved by Places Leisure specifically.

## Status (October 2026)

Re-enabled on 2026-10-28 as its own slow job, not in the shared fast pipeline.

Measured live that day with the crawler's real code path (production venues,
production pacing):

| Sport | Window | Availability requests | Runtime at 3s pacing |
|---|---|---|---|
| badminton | 10 days | 1,528 | ~76 minutes |
| pickleball | 10 days | 848 | ~42 minutes |
| pickleball | 15 days (production window) | ~1,272 | ~64 minutes |

Request counts are close to linear in the date window, because phase 2 is one
call per timetabled timeslot. Two independent checks confirmed that fan-out
cannot be removed:

- The embedded schedule in phase 1 carries no availability data. Every session
  object has exactly `s, e, aId, t, et, al, lc, ag, ti`; a full-page grep finds
  no `status`, `availability`, `spaces`, `capacity` or `remaining` keys.
- The availability endpoint has no bulk mode. `endDate`, `dateRange`, `days`,
  `page` and `take` are all ignored, a date-only `startDate` returns
  `{"success":false,"errors":["Failed to get availability"]}`, and dropping
  `activityId` or `locationId` returns "availability service is currently
  slow". `startDate` cannot be repeated or comma-separated.

Rate limiting from a residential/office IP in that same test was far milder
than the 2026-08-30 GitHub Actions run: 0 of 55 attempts 429'd at 3s, 6 of 66
on a repeat, and 0 of 14 at both 1.0s and 0.3s on a single venue. 429s were
always recovered by the built-in retry and never lost a slot. That is why the
fix is architectural rather than another pacing constant: the provider is not
hard-blocked, it is simply too slow to share a 15-minute budget.

One caveat from a later verification run: after roughly 40 minutes of
continuous testing against this provider from the same IP, 1s pacing started
producing 429s on most first attempts even though the earlier short 1.0s run
was clean. That points at a rolling-window score rather than a per-request
limit, which is a second reason the production job keeps a conservative
starting pace.

A follow-up experiment settled it. Five transports (httpx HTTP/1.1, httpx
HTTP/2, curl_cffi chrome136, curl_cffi safari180, and a full browser header
set) were interleaved 100 requests deep and produced byte-identical status
sequences, each variant's first 429 landing on its own request 7. The 429s
came in 10-request bursts exactly 60 seconds apart, and none occurred below
31 requests in the trailing minute. So the limit is an IP-scoped sliding
window of ~30 requests per 60 seconds, not a bot score. Consequences:

- Transport changes are pointless here. Plain `httpx` HTTP/1.1 is fine.
- HTML centre-page fetches do not consume the API budget. Pages returned 200
  while API calls were still 429ing, so only availability calls need pacing.
- The endpoint sends no `ETag`, `Last-Modified` or `Cache-Control`, so
  conditional requests and 304 revalidation are not available.
- 2.1s is the safe floor (28.6 req/min). 1.8s sustains 33/min, which trips the
  window roughly once a minute.
- There is no cheap bulk shape to find. No two `startDate` values returned
  identical bodies, and although only 9 distinct court-status vectors appeared
  across 40 sampled calls, the bodies differ by an embedded `bookableFrom`
  timestamp.

Given that, the crawler now adapts instead of guessing: `AdaptivePacer` starts
at 3.0s, speeds up 5% after 20 clean requests down to a 2.1s floor, and backs
off 1.5x on any 429 up to 8.0s. The settled interval is logged at the end of
the run, so the first GitHub Actions execution will report that runner's real
budget. Already-started sessions are skipped before any availability call
(they were ~15% of a 3 day window when measured at midday), and half of the
sampled slots at Chessington returned zero availability.

**Current shape:** `python sportscanner/crawlers/pipeline.py --task placesleisure`
runs both sports in one process (so they share the single `_paced_get` rate
limiter) over a 3 day window, and
`.github/workflows/places-leisure-pipeline.yml` triggers it every 2 hours with
its own concurrency group and a 90 minute timeout. Three days is the freshness
trade: it covers everything bookable this week while keeping a run around 35
to 45 minutes. The job exits non-zero if either sport returns no slots.
Verified end-to-end on 2026-10-28 with writes stubbed: 153 badminton and 89
pickleball slots for a single day, routed to their own master tables.

**Current shape:** `python sportscanner/crawlers/pipeline.py --task placesleisure`
runs both sports in one process (so they share the single `_paced_get` rate
limiter) over a 3 day window, and
`.github/workflows/places-leisure-pipeline.yml` triggers it every 2 hours with
its own concurrency group and a 90 minute timeout. Three days is the freshness
trade: it covers everything bookable this week while keeping a run near ~35
minutes. The job exits non-zero if either sport returns no slots.

Two caveats found while re-testing:

- A whole-site 503/stall used to be swallowed by `_fetch_schedule`, which
  returned `[]` and made a dead provider look like a clean run with no
  sessions. That path now raises so the venue is reported as failed.
- Roehampton Sports and Fitness Centre is tagged pickleball in `venues.json`
  but its schedule contains zero pickleball sessions. The tag is stale; the
  crawler handles it, the venue just never produces pickleball rows.

## Status (July 2026)

Confirmed live through the real crawler classes (constructed against
in-memory `SportsVenue` objects matching the `venues.json` entries below,
since this was verified before the DB write): 227 badminton slots across all
8 venues, 170 pickleball slots across all 6 pickleball-offering venues, real
mixed availability (not all-zero or all-full).
