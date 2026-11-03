# Playtomic

London and Greater London venues plus a national Playtomic inventory: padel,
tennis and pickleball. `https://playtomic.com`.
Code: `sportscanner/crawlers/parsers/playtomic/`.

## API shape

Base: `GET https://playtomic.com/api/clubs/availability?tenant_id={uuid}&date=YYYY-MM-DD&sport_id={sport}`

`tenant_id` is a stable UUID assigned once when a club registers on Playtomic and never changes, hardcoded in `SLUG_TO_TENANT_ID` (`playtomic/core/strategy.py`). To find a new venue's `tenant_id`: inspect the club's public page network requests or HTML payload.

Response is a flat JSON array of per-court resources, aggregated by `(start_time, duration)` across courts in `_resources_to_unified()`. `spaces` reflects how many courts are bookable at that exact slot, not a single court's availability.

Booking URLs need a separate slug: the API's `tenant_id`/slug (stored as `venue.slug` in `venues.json`) does not always match the public website URL. Some tenant slugs have trailing dashes or different naming conventions from `playtomic.com/clubs/{slug}`. `_BOOKING_SLUG_OVERRIDES` maps the API slug to the correct public slug; a value of `None` means no working public page exists for that venue at all.

**This provider does not use `BaseCrawler`'s per-venue request loop.** Like Matchi, Playtomic's availability API is queried by `tenant_id` param rather than a per-venue URL path, so Playtomic crawlers override `ScraperCoroutines` directly and drive `PlaytomicAvailabilityFetcher.fetch_venue_date()` with bounded concurrency via `asyncio.Semaphore`.

## WAF and Proxy Fallback

Playtomic availability API uses CloudFront WAF rate limiting and TLS fingerprint validation. Requests carry browser headers (`_HEADERS` in `playtomic/core/strategy.py`). On HTTP 403 or 429 status codes, `fetch_venue_date()` retries through `get_with_proxy_fallback_on_403()` in `crawlers/anonymize/proxies.py`, which retries direct httpx first, then curl_cffi, cycling through `next_impersonate_profile()`'s rotation (`chrome136`, `safari180`, `firefox135`, `chrome124`) once per remaining attempt. This is what usually rescues GitHub Actions runs (Python's ssl handshake is an automatic WAF fail from datacenter IPs).

A small number of specific venues/tenants (confirmed live: Kensington Tennis Club venues, Tennis England Club, on some runs) still exhaust every rotation profile and get 403 on every date in a run, even though other Playtomic venues succeed in the same run from the same runner IP. That points at a per-tenant WAF rule (rate-based or bot-score) rather than a purely IP- or fingerprint-based block — TLS impersonation can't fix a rule that specifically penalizes traffic to that URL/tenant_id combination regardless of handshake. If this keeps recurring for the same venues, the next lever to pull is request pacing/concurrency for just those tenant_ids, not more fingerprint variety.

## Residential padel refresh

Playtomic padel is disabled in the shared pipeline (`PLAYTOMIC_PADEL_ENABLED=False`) because the national venue list made the padel job slow enough to stall. It runs from `sportscanner/crawlers/local_residential.py` on the laptop, via `uk.co.sportscanner.residential-crawl-playtomic` every 30 minutes.

The worker does not sweep every venue every run. It selects a paced rotation:

- London and Greater London venues first, national venues fill the remaining slots.
- Per-venue attempt timestamps in `~/Library/Logs/sportscanner/residential-crawl-state.json` advance the rotation even when a venue returns no slots. The old query selected the 131 venues with no padel rows on every run, which starved everything else.
- Today and tomorrow are fetched for every selected venue. The mid-week and far date tiers are fetched for the first `PLAYTOMIC_EXTENDED_VENUES` in each batch when those tiers are due.
- Requests are globally paced (`PLAYTOMIC_MIN_REQUEST_INTERVAL_SECONDS`, default 2s), and the TLS retry stage is capped at one attempt (`PLAYTOMIC_TLS_ATTEMPTS=1`) so a 403 does not turn into four more requests against the same rate-limit window.
- Each request is capped at 10s and each venue at 120s (`PLAYTOMIC_REQUEST_TIMEOUT_SECONDS`, `PLAYTOMIC_VENUE_TIMEOUT_SECONDS`), so a stalled connection cannot hold the whole run.
- An empty HTTP 200 advances the rotation and does not set a cooldown. Only consecutive 403/429 responses stop the run and set a 30-minute `blocked_until`.
- Indoor/outdoor metadata is cached on disk at `~/.cache/sportscanner/playtomic-indoor.json` for 7 days, and is only fetched when the availability response contains courts. A cold run therefore spends far fewer requests on club pages.

## Duplicate venue cleanup

Twelve venues were stored twice: once under the API tenant_uid slug (trailing dashes, triple dashes, or an `@`) and once under the public website slug. Both rows point at the same Playtomic tenant, so the crawler fetched the same availability twice and the search API rendered two cards for one venue, often with different `last_refreshed` values. The twelve are Battersea Park, Padel People Wimbledon, Padel Social Club Earl's Court and The O2, Powerleague Mill Hill and Shoreditch, Rocks Lane Dyrham Park, Rocks Lane Barnes, Rocks Lane Chiswick, Tour Padel Avery Hill, Padel District Waltham Abbey, and PADEL PADEL Eltham.

`scripts/dedupe_playtomic_venues.py` deletes the legacy slot rows and empties the legacy `sports` array. The `sportsvenue` row is kept so an existing favourite's `composite_key` still resolves on the venue page, but it no longer appears in sport-scoped search queries. `venues.json` contains only the canonical slugs, and `SLUG_TO_TENANT_ID` no longer maps the legacy ones.

The manual `Dedupe Playtomic venues` GitHub Actions workflow runs the same script from a GitHub runner, which is useful when the laptop's current IP is not on the Aiven allowlist.

The same script also renamed three rows that had been seeded under synthetic slugs which do not resolve on playtomic.com: `s3-padel-finchley-road` to `s3-finchley-rd`, `padelhub-kt19-epsom` to `the-padel-hub-kt19-epsom`, and `essendon-padel-club` to `essendon-country-club-uk`. Their tenant ids were confirmed from the public club pages.

## Tennis

Identical API and response shape to padel: `sport_id=TENNIS`. Response schema (`PlaytomicResource`/`PlaytomicSlot`, `playtomic/core/schema.py`) is shared across all sports.

`PlaytomicTennisCrawler` (`playtomic/tennis/scraper.py`) reuses the shared `SLUG_TO_TENANT_ID` map (tenant_id identifies the club, not the sport) and `PlaytomicAvailabilityFetcher` configured with `sport_id=TENNIS_SPORT_ID, category="Tennis"`.

Tennis venues verified on Playtomic:
- Tennis England Club (`open-jan-2025-tennis-england-club`, `2a31c6ce-b212-4448-abd2-b05a6bbde784`): 8 tennis courts, ~£16 to £20/hr
- Rocks Lane - Barnes (`rocks-lane---barnes`, `e2ec82b3-3862-4e42-90bb-bb41f59e737d`): 4 tennis courts, ~£15 to £23/hr
- Rocks Lane - Chiswick (`rocks-lane---chiswick`, `9c95ac87-5273-47a9-bf67-342c566caf79`): tennis availability
- Kensington Tennis Club - Holland Park Villas (`kensington-tennis-club-holland-park-villas-indoors-outdoors`, `17073a7b-e226-484a-82cf-d2ca0dab9751`): 2 courts, ~£20 to £35/hr
- Kensington Tennis Club - King's Road (`kensington-tennis-club-kings-road`, `6e4e1447-5ed3-44ec-98c5-5a202e98e251`): 1 court, ~£38/hr

## Pickleball

Identical API and response shape to padel and tennis: `sport_id=PICKLEBALL`.

`PlaytomicPickleballCrawler` (`playtomic/pickleball/scraper.py`) follows the shared pattern: shared `SLUG_TO_TENANT_ID`, shared `PlaytomicAvailabilityFetcher` constructed with `sport_id=PICKLEBALL_SPORT_ID, category="Pickleball"`.

Pickleball venues verified on Playtomic:
- West London Pickleball Club (`west-london-pickleball-club`, `2af6b5fa-0c25-414b-87ae-93032eea1084`): 4 courts, ~£20/hr
- Kensington Pickleball Club (Indoors & Outdoors) (`kensington-pickleball-club-indoors-outdoors`, `40805261-42ab-41b9-b35e-73bc5d4f299e`): 2 courts, ~£28/hr
- Racketeer (`racketeer`, `549a1bc8-d63e-43d4-b632-5a313e299845`): 1 court, ~£35 to £55/hr (dual-sport with 13 padel courts)
- Georgians Padel (`georgians-padel`, `7c3575d5-8285-4199-a9e1-961118269bfe`): 2 pickleball courts
- Padel District Waltham Abbey (`padel-waltham-abbey`, `5ccd5197-0083-411e-9e7f-de0a418c5b69`): 2 pickleball courts, ~£12 to £24/hr
- Tennis England Club (`open-jan-2025-tennis-england-club`, `2a31c6ce-b212-4448-abd2-b05a6bbde784`): 4 pickleball courts, ~£18 to £32/hr

## Venues Added August 2026

The following London venues were audited and confirmed live against Playtomic availability API:

| Venue | Slug (= tenant_uid) | Sport(s) | Verified Details |
|---|---|---|---|
| Padel Social Club - Paddington | `padel-social-club-paddington` | padel | 4 padel courts, £80 to £120/hr, W2 6BD |
| West London Pickleball Club | `west-london-pickleball-club` | pickleball | 4 pickleball courts, ~£20/hr, W3 7EN |
| Kensington Pickleball Club | `kensington-pickleball-club-indoors-outdoors` | pickleball | 2 courts, ~£28/hr, indoor and outdoor, W8 7AD |
| Racketeer | `racketeer` | padel, pickleball | 13 padel courts, 1 pickleball court, NW10 6PH |
| Padel Pals - Sydenham | `padel-pals` | padel | 4 padel courts, ~£55 to £105/hr, SE26 4PR |
| Bannatyne Grove Park | `bannatyne-grove-park` | padel | 3 padel courts, ~£30 to £60/hr, SE12 9PN |
| Bannatyne Chafford Hundred | `bannatyne-chafford-hundred` | padel | 3 padel courts, ~£34 to £74/hr, RM16 6YJ |
| Padel Play London | `padel-play-london` | padel | 3 padel courts, ~£53 to £105/hr, N4 1LZ |
| Padel United Willesden | `padel-united-willesden` | padel | 1 padel court, ~£22 to £45/hr, NW10 3QX |
| Powerleague Watford | `powerleague-watford` | padel | 4 padel courts, WD23 2TY |
| Kensington Tennis Club - Holland Park | `kensington-tennis-club-holland-park-villas-indoors-outdoors` | tennis | 2 tennis courts, ~£20 to £35/hr, W8 7EB |
| Kensington Tennis Club - King's Road | `kensington-tennis-club-kings-road` | tennis | 1 tennis court, ~£38/hr, SW10 0HD |
| Ezeepadel Weybridge | `ezeepadel-weybridge` | padel | 4 padel courts, KT13 8QA |
| Epping Golf Course | `epping-golf-course` | padel | 1 padel court, CM16 7NJ |

Venue additions are saved to `app-crawlers/reports/venue-fragments/playtomic.json`.

## Audited but not added on Playtomic

- **S3 Padel @ The Liberty Romford**: announced in press but no public Playtomic tenant or booking presence active as of August 2026. Re-check when bookings open.
- **Padel Social Club Kentish Town**: advertised as coming soon, no public Playtomic page yet.
- **Stratford Padel Club**: uses Spanish vendor TPC-MatchPoint (`stratfordpadelclub.matchpoint.com.es`), not Playtomic. Covered by dedicated crawler under `sportscanner/crawlers/parsers/stratfordpadel/`.
- **Existing venues verified**: Padel Box Bermondsey, S3 Padel Wembley (`wembley-padel`), The Hive London (`the-hive-london`), Rocks Lane Barnes, Rocks Lane Chiswick, Padel Social Club Earl's Court and The O2, The 108, Tour Padel Avery Hill.

## Booking Slug Overrides

Remaining `_BOOKING_SLUG_OVERRIDES` in `strategy.py` for API slugs that differ from the public club page:
- `padel-4-everyone---noak-hill`: `padel4everyone-harold-hill-central-park`
- `the-padel-hub-n20-ltd`: `the-padel-hub-n20-north-london`
- `brent-x`: `social-sports-brent-cross`
- `wembley-padel`: `social-sports-wembley`

The duplicate API/website slug pairs (Battersea, Padel People Wimbledon, Padel Social Club Earl's Court and The O2, Powerleague Mill Hill and Shoreditch, Rocks Lane Dyrham Park, Rocks Lane Barnes, Rocks Lane Chiswick, Tour Padel Avery Hill, Padel District Waltham Abbey, PADEL PADEL Eltham) now use only the canonical public slug, so they need no override.
