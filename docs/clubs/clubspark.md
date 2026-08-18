# LTA ClubSpark

6 venues (starting seed — expected to grow), `https://clubspark.lta.org.uk`. Tennis.
Code: `sportscanner/crawlers/parsers/clubspark/`.

## API shape

Base: `GET https://clubspark.lta.org.uk/v0/VenueBooking/{VenueSlug}/GetVenueSessions?resourceID=&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&roleId=`

Unauthenticated — no auth headers, cookies, or tokens required for read access,
confirmed live. A companion endpoint,
`GET /v0/VenueBooking/{VenueSlug}/GetSettings`, returns venue metadata (roles,
resource categories, timezone) and is the right way to verify a candidate slug
before adding it to `venues.json` — guessed slugs (e.g. from a park's common
name) 404 silently rather than falling back to anything useful. Confirmed
404s during discovery: `ClissoldPark`, `HollandParkLTC`, `LondonFieldsLTC`.

The discovery method: the venue's booking HTML page is a thin client-rendered
shell with no embedded JSON — the actual API URL template lives in a shared
minified JS bundle (`comp-core.js`) served identically to every venue. Once
decoded once, the pattern applies to any ClubSpark venue by slug substitution;
no per-venue reverse-engineering is needed.

### Response shape

```json
{
  "TimeZone": "Europe/London",
  "Resources": [
    {"ID": "...", "Name": "Court 1", "Days": [
      {"Date": "2026-08-20T00:00:00", "Sessions": [
        {"Category": 1000, "Name": "Booking", "StartTime": 450, "EndTime": 480,
         "Interval": 30, "CourtCost": 3.80},
        {"Category": 8000, "Name": "Closed", ...},
        {"Category": 2000, "Name": "Adult Beginners (NTA)", ...}
      ]}
    ]}
  ]
}
```

`StartTime`/`EndTime` are minutes-from-midnight (converted to `time` in
`ClubSparkTennisResponseParserStrategy.parse`). `Category` distinguishes real
availability from noise: `1000` = genuinely bookable, `8000` = closed,
`2000` = occupied by a coaching/programmed session. Only `1000` rows are
emitted as slots — everything else is deliberately dropped, not a parsing gap.

## Why this bypasses `BaseCrawler`'s default fetch loop

`GetVenueSessions` takes a `startDate`/`endDate` **range** and returns every
day in between in one call — unlike the venue × single-date shape
`BaseCrawler`'s default loop assumes. `ClubSparkTennisCrawler` overrides
`ScraperCoroutines` (same precedent as Matchi/CitySport/Playtomic, each for
their own API-shape reasons — see their respective docs) to issue **one
request per venue** covering `min(dates)..max(dates)`, rather than one
request per venue per date. This is meaningfully cheaper than the standard
loop would be here, not just a shape workaround.

## Cloudflare bot management

Responses set a `__cf_bm` cookie. Moderate/occasional polling (the standard
per-provider concurrency cap, a realistic desktop Chrome `User-Agent`) worked
cleanly during research; a naive high-volume crawler risks Cloudflare
challenges. No proxy is needed — this endpoint works fine unproxied.

## Venue list (starting seed, verified live)

| Slug | Notes |
|---|---|
| `SouthwarkPark` | Southwark Park, Bermondsey |
| `VictoriaParkLONDON` | Victoria Park, Hackney/Tower Hamlets border |
| `BatterseaParkTennisCourts` | Battersea Park |
| `QueensParkTennisCourts` | Queen's Park, Brent/Westminster |
| `TennisInSouthwark` | Likely a borough-wide multi-site booking scheme rather than a single physical park — the `Resources` returned may span more than one court location under one venue entry. Address in `venues.json` is deliberately generic; needs a follow-up pass to disaggregate by actual site if that matters for the map view. |
| `CityOfLondonTennis` | Likely tied to a City of London Corporation-managed open space (Corporation runs several London green spaces including Queen's Park). Exact physical site not independently confirmed — address in `venues.json` flagged for verification. |

This list is a **starting point, not exhaustive** — expand by checking
borough tennis-booking pages (Hackney, Islington, Wandsworth, Lambeth, Tower
Hamlets, Camden, Westminster, Merton, Richmond, Greenwich, etc.) for their
linked ClubSpark slug, verifying each via `GetSettings` before adding.

## Status (added August 2026)

Confirmed live during initial research: all 6 seed slugs returned `200` with
real session data from `GetVenueSessions`. **Re-run during end-to-end
verification from a different network got a Cloudflare `403` challenge page
("Just a moment...") on every request instead** — same endpoint, same
headers, same slugs, only the source IP differed. This is IP-reputation-
dependent Cloudflare bot management, the same class of issue already
documented for Matchi/Playtomic/Everyone Active elsewhere in this repo (each
run's IP either passes or gets challenged, not a property of the request
itself). Pipeline wiring, request/response parsing, and DB integration are
all confirmed correct via the other three tennis providers (Better/GLL,
Playtomic, Matchi all returned real parsed data end-to-end in the same
verification pass) — ClubSpark specifically needs its next real scheduled
run (from whatever IP that deploys from) checked before this can be called
fully confirmed. If it's consistently challenged in production too, the fix
is the same one already used for Everyone Active/Matchi/Playtomic: retry via
`get_with_proxy_fallback_on_403` on a 403 rather than treating it as
"no slots" — not yet wired in for ClubSpark since it wasn't known to be
needed until this verification pass.
