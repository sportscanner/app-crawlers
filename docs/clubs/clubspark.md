# LTA ClubSpark

49 verified London park tennis venues in `reports/venue-fragments/clubspark.json`, `https://clubspark.lta.org.uk`. Tennis.
Code: `sportscanner/crawlers/parsers/clubspark/`.

## API shape

Base: `GET https://clubspark.lta.org.uk/v0/VenueBooking/{VenueSlug}/GetVenueSessions?resourceID=&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&roleId=`

Unauthenticated: no auth headers, cookies, or tokens required for public read access. **A `Referer` header pointing at the venue booking page (`https://clubspark.lta.org.uk/{VenueSlug}/Booking/BookByDate`) is mandatory**:
the identical request without it gets a Cloudflare `403`, with it gets `200` (confirmed live). The crawler sends this header on every request via `referer_for_slug()` in `core/strategy.py`.

A companion endpoint, `GET /v0/VenueBooking/{VenueSlug}/GetSettings`, returns venue metadata (roles, resource categories, timezone, authentication flags) and is used to verify a candidate slug: guessed slugs return HTTP `500` or `404` on `GetSettings`, and login-gated venues return `MustAuthenticate: true`.

Rate limiting: aggressive back-to-back probing trips Cloudflare `429` / `403` challenges for the source IP. The crawler routes through `get_with_proxy_fallback_on_403` in `sportscanner/crawlers/anonymize/proxies.py`, which retries against rotating proxy connections if a direct connection is challenged.

Discovery method: the venue booking HTML page is a thin client-rendered shell with no embedded JSON. The API URL template lives in a shared JS bundle served identically to every venue. The pattern applies to any ClubSpark venue by slug substitution.

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

`StartTime` and `EndTime` are minutes from midnight (converted to `time` in `ClubSparkTennisResponseParserStrategy.parse`). `Category` distinguishes real availability from noise: `1000` = genuinely bookable, `8000` = closed, `2000` = coaching/programmed session. Only `1000` rows are emitted as slots.

## Why this bypasses BaseCrawler default fetch loop

`GetVenueSessions` takes a `startDate`/`endDate` range and returns every day in between in one call, unlike the venue x single-date shape `BaseCrawler` default loop assumes. `ClubSparkTennisCrawler` overrides `ScraperCoroutines` to issue one request per venue covering `min(dates)..max(dates)`, rather than one request per venue per date.

## Cloudflare bot management

Responses set a `__cf_bm` cookie. The crawler uses `get_with_proxy_fallback_on_403` in `sportscanner/crawlers/anonymize/proxies.py` to transparently fall back to fresh rotating proxy connections whenever a direct IP is challenged with 403 or 429.

## Verified London Park Tennis Venues (49 venues)

The full organisation fragment is saved to `reports/venue-fragments/clubspark.json` with 49 verified London park tennis venues:

| Borough | Slug | Venue Name | Courts | Notes |
|---|---|---|---|---|
| Hammersmith & Fulham | `RavenscourtPark` | Ravenscourt Park Tennis Courts | 7 | Public anonymous API; booking page login-gated (see below) |
| Hammersmith & Fulham | `SouthParkFulham` | South Park Tennis Courts (Fulham) | 7 | Public anonymous API; booking page login-gated (see below) |
| Hammersmith & Fulham | `HurlinghamPark` | Hurlingham Park Tennis Courts | 3 | Public anonymous API; booking page login-gated (see below) |
| Haringey / Islington | `FinsburyPark` | Finsbury Park Tennis Courts | 8 | Public anonymous API |
| Haringey | `PavilionTennis` | Pavilion Sports (Albert Road Rec) Tennis Courts | 6 | Canonical public slug for Albert Road Rec |
| Haringey | `ChestnutsPark` | Chestnuts Park Tennis Courts | 2 | Public anonymous API |
| Haringey | `BruceCastlePark` | Bruce Castle Park Tennis Courts | 7 | Public anonymous API |
| Haringey | `ChapmansGreen` | Chapmans Green Tennis Courts | 2 | Public anonymous API |
| Southwark | `SouthwarkPark` | Southwark Park Tennis Courts | 4 | Public anonymous API |
| Southwark | `BurgessParkSouthwark` | Burgess Park Tennis Courts | 7 | Canonical public slug; bare `BurgessPark` is login-gated |
| Southwark | `DulwichPark` | Dulwich Park Tennis Courts | 4 | Public anonymous API |
| Southwark | `BelairPark` | Belair Park Tennis Courts | 4 | Belair Park / Gerald FitzGerald courts in West Dulwich |
| Southwark | `BrunswickPark` | Brunswick Park Tennis Courts | 2 | Public anonymous API |
| Hackney | `ClissoldParkHackney` | Clissold Park Tennis Courts | 9 | Canonical public slug for Clissold Park |
| Hackney | `LondonFieldsPark` | London Fields Tennis Courts | 2 | Canonical public slug for London Fields |
| Hackney | `AskeGardens` | Aske Gardens Tennis Courts | 1 | Public anonymous API |
| Lambeth | `ClaphamCommon` | Clapham Common Tennis Courts | 11 | Public anonymous API |
| Lambeth | `KenningtonPark` | Kennington Park Tennis Courts | 9 | Public anonymous API |
| Lambeth | `BrockwellPark` | Brockwell Park Tennis Courts | 6 | Public anonymous API; booking page login-gated (see below) |
| Lambeth | `RuskinPark` | Ruskin Park Tennis Courts | 4 | Public anonymous API |
| Lambeth | `VauxhallPark` | Vauxhall Park Tennis Courts | 2 | Public anonymous API |
| Lambeth | `LarkhallPark` | Larkhall Park Tennis Courts | 2 | Public anonymous API |
| Lewisham | `LadywellFields` | Ladywell Fields Tennis Courts | 5 | Public anonymous API |
| Lewisham | `TelegraphHill` | Telegraph Hill Tennis Courts | 2 | Public anonymous API; booking page login-gated (see below) |
| Lewisham | `ManorHouseGds` | Manor House Gardens Tennis Courts | 2 | Canonical public slug for Manor House Gardens |
| Lewisham | `MayowPark` | Mayow Park Tennis Courts | 2 | Public anonymous API |
| Merton | `WimbledonPark` | Wimbledon Park Tennis Courts | 20 | Largest venue in the set |
| Merton | `MordenPark` | Morden Park Tennis Courts | 4 | Public anonymous API |
| Merton | `KingGeorgesPlayingFields` | King George's Playing Fields Tennis Courts | 3 | Public anonymous API |
| Wandsworth | `BatterseaParkTennisCourts` | Battersea Park Tennis Courts | 16 | Public anonymous API |
| Brent | `QueensParkTennisCourts` | Queen's Park Tennis Courts | 6 | Public anonymous API |
| Brent | `GladstoneParkTennis` | Gladstone Park Tennis Courts | 11 | Canonical public slug; bare `GladstonePark` is login-gated |
| Brent | `ChelmsfordSquare` | Chelmsford Square Tennis Courts | 4 | Public anonymous API |
| Barnet | `HendonPark` | Hendon Park Tennis Courts | 6 | Public anonymous API |
| Barnet | `LytteltonPlayingFields` | Lyttelton Playing Fields Tennis Courts | 3 | Public anonymous API; booking page login-gated (see below) |
| Richmond upon Thames | `OldDeerPark` | Old Deer Park Tennis Courts | 5 | Public anonymous API |
| Richmond upon Thames | `PalewellCommon` | Palewell Common Tennis Courts | 4 | Public anonymous API |
| Richmond upon Thames | `SheenCommon` | Sheen Common Tennis Courts | 4 | Public anonymous API |
| Richmond upon Thames | `CambridgeGardens` | Cambridge Gardens Tennis Courts | 4 | Public anonymous API |
| Greenwich | `KidbrookeGreen` | Kidbrooke Green Park Tennis Courts | 2 | Public anonymous API |
| Greenwich | `PlumsteadCommon` | Plumstead Common Tennis Courts | 3 | Public anonymous API |
| Hounslow | `LamptonPark` | Lampton Park Tennis Courts | 8 | Public anonymous API |
| Barking & Dagenham | `BarkingPark` | Barking Park Tennis Courts | 6 | Public anonymous API |
| Barking & Dagenham | `StChadsPark` | St Chad's Park Tennis Courts | 4 | Public anonymous API |
| Redbridge | `ValentinesPark` | Valentines Park Tennis Courts | 8 | Public anonymous API |
| Redbridge | `GoodmayesPark` | Goodmayes Park Tennis Courts | 4 | Public anonymous API |
| Redbridge | `RayPark` | Ray Park Tennis Courts | 2 | Public anonymous API |
| Enfield | `BroomfieldPark` | Broomfield Park Tennis Courts | 9 | Public anonymous API |
| Enfield | `GrovelandsPark` | Grovelands Park Tennis Courts | 2 | Public anonymous API |

## Login-Gated Booking Pages (booking_url fallback)

Six of the 49 tracked venues server-side redirect their `/Booking/BookByDate`
page to LTA Play login (`.../{slug}/Booking/LTAPlayLogin`) instead of showing
the availability calendar anonymously: `RavenscourtPark`, `SouthParkFulham`,
`HurlinghamPark`, `BrockwellPark`, `TelegraphHill`, `LytteltonPlayingFields`.
Confirmed venue by venue across all 49 venues in August 2026 via curl_cffi
chrome impersonation; plain curl sees the same 302, so this is ClubSpark's own
per-council routing configuration, not a Cloudflare artifact. Their
`GetSettings` still reports `MustAuthenticate: false` and their underlying
`GetVenueSessions` JSON API still serves real availability anonymously, so
they remain in scope: only the deep link is gated.

For these six, `booking_url_for_slug()` in `core/strategy.py` points
`booking_url` at the venue's public home page (`/{slug}`), which loads fine
without an account and links out to booking, rather than dumping a user on an
LTA Play registration screen under this venue's name.

## Dropped and Login-Gated Venues

The following candidates were investigated and excluded per the public availability scope rule:

- `GreenwichPark` (Greenwich Park Tennis Courts): viewing redirects to `auth.clubspark.uk` login.
- `TannerStreetPark` (Tanner Street Park, Southwark): `MustAuthenticate: true` on settings endpoint.
- `SpringfieldPark` (Springfield Park, Hackney): `MustAuthenticate: true` on settings endpoint.
- `HammersmithPark`, `ShoreditchPark`: viewing redirects to `auth.clubspark.uk` login.
- `HackneyTennis` and `TennisInSouthwark`: borough scheme shells with 0 court resources.
- `CityOfLondonTennis`: shell with 0 court resources.
- `CherryTreeWood` (Barnet): serves 404 / NotFound.

## Verification Results

End-to-end test execution of `ClubSparkTennisCrawler._crawl_async` across all 49 venues for a 3-day window yielded 2,272 parsed `UnifiedParserSchema` slots with realistic prices ranging from free community slots (£0.00) to standard £4.00-£15.00 rates. All postcodes and coordinates have been validated with Postcodes.io.
