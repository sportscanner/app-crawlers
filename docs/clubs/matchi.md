# Matchi

22 padel venues + 3 tennis venues, `https://www.matchi.se`. Padel, tennis.
Code: `sportscanner/crawlers/parsers/matchi/`.

## API shape

Base: `GET https://www.matchi.se/book/listSlots?wl=&facility={facilityId}&date=YYYY-MM-DD&sport=5`
(`sport=5` is padel, `sport=1` is tennis). Returns HTML (not JSON): a fragment with `button.btn-slot`
elements per bookable slot, parsed with BeautifulSoup in `_parse_listslots_html()`.

Facility IDs are stable numeric DB identifiers hardcoded in
`SLUG_TO_FACILITY_ID` and `TENNIS_SLUG_TO_FACILITY_ID` (`matchi/core/strategy.py`).

**This provider does not use `BaseCrawler`'s per-venue request loop at all.**
Matchi's endpoint iterates by date across all venues in one shape, not by
per-venue URL, so `MatchiPadelCrawler` overrides `ScraperCoroutines` directly and
`MatchiSlotFetcher.crawl_date()` fans out over facilities itself.

### Timestamps: Stockholm local time, not UTC, not London time

`/book/listSlots` timestamps are true Unix milliseconds UTC, but Matchi's backend
encodes UK venue slot times as if they were Stockholm wall-clock time (CEST in
summer, CET in winter) rather than the venue's actual London time. Stockholm is
always exactly UTC+1 ahead of London, year-round (no DST edge case between them,
since UK and Sweden change clocks on the same dates), so extracting the
Stockholm-local hour/minute directly gives the correct London booking time. This
is intentional, not a bug, and matches what the Matchi website itself displays.
Converting UTC to Europe/London directly would introduce a spurious 1-hour offset.
See `_ms_to_booking_time()` and the module docstring in `matchi/core/strategy.py`
for the full reasoning.

An older `/book/findFacilities` endpoint (removed, see git history) embedded
genuinely Stockholm-local timestamps for a different reason and caused a real
1-hour lag bug: that prompted the switch to `/book/listSlots`.

## Fixed July 2026: site-wide 403s from unbounded concurrency and no headers

Because Matchi bypasses `BaseCrawler`'s semaphore-bounded fetch loop, it used to
fire all dates and facilities concurrently with zero pacing (up to ~100
simultaneous requests in one burst) and with no headers at all (not even a
`User-Agent`; httpx's bare default). Matchi's WAF was blocking every single
request outright as a result: every facility, every date, HTTP 403, for every
scheduled run.

Fixed by:
1. Adding browser-like headers (mobile Safari `User-Agent`, `accept`, `accept-language`).
2. Wrapping each facility fetch in an `asyncio.Semaphore` sized to the existing
   `CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER` setting, threaded down from
   `MatchiPadelCrawler._crawl_async` through `crawl_date()` to
   `_fetch_facility_slots()`.

## Fixed July 2026: 2 specific facilities still 403 in a minority of runs

After the fix above, two facilities (`westhertssportsclub` and `towerhillterrace`)
kept getting HTTP 403 on every date within a run in ~4 of 10 consecutive scheduled
runs. Matchi and Playtomic run in the same crawler pipeline job and share one
GitHub Actions runner IP per run. Whether that run's IP happens to already be
blocklisted by Matchi's WAF for these two facilities is IP-dependent.

Fixed via proxy fallback: on HTTP 403 from the direct connection,
`_fetch_facility_slots` retries against a fresh
`httpxAsyncClientWithProxyRotation()` connection up to 4 times before giving up.
The retry helper (`get_with_proxy_fallback_on_403` in `crawlers/anonymize/proxies.py`)
is shared with Playtomic. Any non-403 error is raised immediately.

## Known-unbookable venues (not crawler bugs)

Two facilities return zero rows every run, deliberately, confirmed by
fetching `/book/listSlots` directly and reading the HTML body:

- **Cumberland Lawn Tennis Club** (`cltc`, facility 2466): body reads
  `"Only members may book sessions."` (members-only, not publicly bookable).
- **St Paul's Cathedral Churchyard** (`stpaulscathedralchurchyard`, facility
  2995): body reads `"Not available for booking."`

Neither returns an HTTP error: both are 200s with a message div instead of
slot buttons, so `_parse_listslots_html()` correctly finds zero `btn-slot`
elements and returns an empty list.

## Venue expansion (August 2026)

Discovery method: `POST https://www.matchi.se/facilities/findFacilities` with payload
`{"lat": "51.5074", "lng": "-0.1278", "asJson": "true"}` returns the complete JSON
registry of facilities (`facilities` and `restOfFacilities`), containing facility IDs,
slugs, names, exact coordinates, postcodes, and addresses.

### Added London and Commuter Venues

All verified anonymously viewable via `/book/listSlots` with live bookable slot buttons:

1. **PDL Padel United - North London - Bushey** (`padelunitedbushey`, facility 2188,
   Bushey Grove Leisure Centre, Aldenham Rd, WD23 2TD): Padel (sport 5), 3 indoor courts.
2. **Game4Padel | Bloom Heathrow London** (`game4padelheathrow`, facility 2370,
   Feltham, TW14 8HA): Padel (sport 5), 2 covered courts.
3. **Game4Padel | Broxbourne Sports Club** (`game4padelbroxbourne`, facility 1718,
   Mill Lane Close, Broxbourne, EN10 7BA): Padel (sport 5), 2 outdoor courts.
4. **Game4Padel | Gosling** (`game4padelgosling`, facility 2369,
   Stanborough Rd, Welwyn Garden City, AL8 6XE): Padel (sport 5), 2 courts.
5. **Game4Padel | Chesham 1879** (`game4padelchesham`, facility 2438,
   Cameron Road, Chesham, HP5 2JU): Padel (sport 5), 2 courts.
6. **Brentwood Padel Club** (`brentwoodpadeclub`, facility 2706,
   Childerditch Lane, Warley, Brentwood, CM13 3FD): Padel (sport 5), 3 outdoor courts.
7. **Epping and Ongar Padel** (`eppingandongarpadel`, facility 3182,
   Mount Farm, Theydon Mount, Epping, CM16 7PX): Padel (sport 5), 4 courts.
8. **Forest Smash Padel** (`forestsmashpadel`, facility 3173,
   Forest Hall, Hatfield Broad Oak, Bishops Stortford, CM22 7BT): Padel (sport 5), 2 courts.
9. **Down Hall Hotel Spa & Estate** (`downhallhotel`, facility 1313,
   Matching Road, Hatfield Heath, Bishops Stortford, CM22 7AS): Padel (sport 5) AND
   Tennis (sport 1), 1 padel court + 1 tennis court. First live confirmed Matchi tennis venue.
10. **BSLTC (Bishop's Stortford Lawn Tennis Club)** (`bsltc`, facility 2584,
    Cricketfield Lane, Bishop's Stortford, CM23 2TD): Padel (sport 5), 1 court.
11. **Country Padel Co** (`countrypadelco`, facility 3043,
    Dowsetts Farm, Colliers End, Ware, SG11 1EF): Padel (sport 5), 3 courts.
12. **Frindsbury Tennis and Padel Club** (`frindsburytennisandpadelclub`, facility 2865,
    Frog Island, Upnor Road, Frindsbury, Rochester, ME2 4HE): Padel (sport 5), 3 courts.

### Other Venue Investigation Outcomes

- **PDL Padel United Erith (Bexley)**: Not on Matchi. Booking is hosted on Playtomic
  (`https://playtomic.com/clubs/padel-united-erith`).
- **PadelStars**: Not on Matchi. Uses MatchPoint app / platform (`padelstars.co.uk`).
- **Already integrated (London)**: Coldharbour (`game4padelgll`, 2636), Tower Hill
  (`towerhillterrace`, 2996), Hay's Galleria (`londonbridgecity`, 3041), The Padel Yard
  Vauxhall (`g4pvauxhallpadelyard`, 3011), Crystal Palace (`game4padelcrystalpalace`, 2368),
  West Herts (`westhertssportsclub`, 3178), The Padel Yard Wandsworth (`g4pthepadelyard`, 2322),
  Parkside Southall (`game4padelparkside`, 2573).

Venue entries for all 12 additions are written to `reports/venue-fragments/matchi.json`.

## Tennis (updated August 2026)

`sport=1` is tennis (`sport=5` is padel).

`MatchiSlotFetcher` (`matchi/core/strategy.py`) accepts `sport_id`, `category`,
`facility_ids`, and `default_price` as constructor parameters, so `MatchiTennisCrawler`
(`matchi/tennis/scraper.py`) reuses the same fetch and parse machinery with
`TENNIS_SPORT_ID`, `"Tennis"`, and `TENNIS_SLUG_TO_FACILITY_ID`.

**Live populated slot response confirmed**:
- **Down Hall Hotel Spa & Estate** (`downhallhotel`, facility 1313): Publicly bookable
  with 14 slots per day (98 slots over 7 days).

Other tennis facilities:
- **Putney Lawn Tennis Club** (`putneylawntennisclub`, facility 2052): Members-only,
  cleanly returns zero slots.
- **Frindsbury Tennis and Padel Club** (`frindsburytennisandpadelclub`, facility 2865):
  one Matchi facility covering both sports (6 padel + 6 tennis courts, Frog Island ME2 4HE).
  Padel slots confirmed live; tennis is not available for online booking (zero slot buttons
  across checked dates), so the tennis mapping is kept but may stay empty. The legacy slug
  `frindsburytennisandpadel` now 302-redirects to the facilities index and was removed from
  venues.json to avoid a duplicate venue row.
