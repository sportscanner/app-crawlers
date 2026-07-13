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
renders as an near-empty stub without an authenticated session). `price` is
set to the literal string `"Check website"` rather than guessed. Revisit if a
pricing source turns up.

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

## Status (July 2026)

Confirmed live through the real crawler classes (constructed against
in-memory `SportsVenue` objects matching the `venues.json` entries below,
since this was verified before the DB write): 227 badminton slots across all
8 venues, 170 pickleball slots across all 6 pickleball-offering venues, real
mixed availability (not all-zero or all-full).
