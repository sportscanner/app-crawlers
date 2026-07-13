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
plain `httpx` gets a clean `200` from a non-GitHub-Actions connection
(confirmed: CitySport needs `curl_cffi` impersonation to get past a JA3-based
block; UEL doesn't).

**But it is soft-blocked from GitHub Actions runner IPs specifically** —
confirmed on the first two production runs after this venue was added: all
10/10 requests failed with `ReadTimeout`, not a clean error status, while the
identical request succeeds in well under a second from any other connection.
Same class of problem as [Everyone Active](everyone-active.md) (GitHub's
hosted-runner IP ranges being blocked), just manifesting as a silent hang
instead of an explicit 403. Since there's no clean error to trigger a
try-direct-first fallback on (direct connections don't fail fast, they just
sit there until they time out), `UELSportsDockCrawler` bypasses `BaseCrawler`'s
shared fetch loop entirely and routes straight through the rotating proxy with
retry (up to 4 attempts per request) — skipping the direct attempt rather than
wasting a timeout on it first. Confirmed live end-to-end after the fix.

Low request volume here (1 venue, 10 requests/run) keeps this cheap relative
to Everyone Active's 120/run, so it doesn't meaningfully compete for the
shared proxy pool's capacity.

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
