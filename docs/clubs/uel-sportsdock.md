# UEL SportsDock

1 venue, `https://www.uel.ac.uk`. Badminton.
Code: `sportscanner/crawlers/parsers/uelsportsdock/`.
Added July 2026.

## API shape

Base: `GET https://horizons.uel.ac.uk/LhWeb/en/api/Sites/1/Timetables/ActivityBookings?date=YYYY/MM/DD&pid=0`

Runs on the same "Leisure Hub" (`LhWeb`) vendor platform as
[CitySport](citysport.md) — confirmed by an exact field-for-field match against
`CitySportsResponseSchema` (same JSON shape, same field names/types). The
booking portal (`horizons.uel.ac.uk/lhweb/identity/login`) requires an account
to actually complete a booking, but the timetable/availability API itself is
fully public and anonymous — no auth needed to view slots, same as CitySport.

**Unlike CitySport, this instance is not behind a TLS-fingerprinting WAF** —
plain `httpx` gets a clean `200` (confirmed: CitySport needs `curl_cffi`
impersonation to get past a JA3-based block; UEL doesn't). So
`UELSportsDockCrawler` uses `BaseCrawler`'s standard fetch loop directly,
unlike CitySport's `ScraperCoroutines` bypass.

### Badminton filter differs from CitySport

CitySport identifies badminton via `ActivityGroupDescription == "Badminton"`.
UEL files badminton under a generic `ActivityGroupDescription == "Court"`
instead — `DisplayName == "Badminton"` is what actually identifies it here.
Both venues share the same platform but their own site admins configure
activity groupings independently, so don't assume this filter transfers to a
third LhWeb-based venue without checking a live response first.

### Date window

No per-venue date-window narrowing (`delta=None` in `coroutines()`) — confirmed
live that the API returns valid data 3+ weeks out without erroring, unlike
Better/GLL-style providers that reject far-future dates with a 422.

## Discovery note

Found by researching `uel.ac.uk/study/campus-life/sport/sportsdock/courts-sportsdock`
(itself behind the same TLS-fingerprinting-style block the main `uel.ac.uk`
site uses — needed `curl_cffi` just to read the page). The page links to the
booking portal only as generic "online portal" text; the actual `LhWeb` URL
had to be pulled from the page's raw HTML (`grep`-ing for `href` near "online
portal"), and the anonymous timetable API endpoint was found by pattern-matching
CitySport's already-known URL shape against the new domain.

## Status (July 2026)

Confirmed live end-to-end through the real `coroutines()` entry point: 110
slots across a 5-day window, 97 with real availability.
