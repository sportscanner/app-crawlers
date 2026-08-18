# Matchi

10 padel venues + 2 tennis venues, `https://www.matchi.se`. Padel, tennis.
Code: `sportscanner/crawlers/parsers/matchi/`.

## API shape

Base: `GET https://www.matchi.se/book/listSlots?wl=&facility={facilityId}&date=YYYY-MM-DD&sport=5`
(`sport=5` is padel). Returns HTML (not JSON) — a fragment with `button.btn-slot`
elements per bookable slot, parsed with BeautifulSoup in
`_parse_listslots_html()`.

Facility IDs are stable numeric DB identifiers hardcoded in
`SLUG_TO_FACILITY_ID` (`matchi/core/strategy.py`). To find one: visit
`matchi.se/facilities/{slug}` and read `facilityId=<n>` out of the inline JS.

**This provider does not use `BaseCrawler`'s per-venue request loop at all.**
Matchi's endpoint iterates by date across *all* venues in one shape, not by
per-venue URL, so `MatchiPadelCrawler` overrides `ScraperCoroutines` directly and
`MatchiSlotFetcher.crawl_date()` fans out over facilities itself. Same pattern as
Playtomic (below) — see that file for why this matters.

### Timestamps: Stockholm local time, not UTC, not London time

`/book/listSlots` timestamps are true Unix milliseconds UTC, but Matchi's backend
*encodes UK venue slot times as if they were Stockholm wall-clock time* (CEST in
summer, CET in winter) rather than the venue's actual London time. Stockholm is
always exactly UTC+1 ahead of London, year-round (no DST edge case between them,
since UK and Sweden change clocks on the same dates), so extracting the
Stockholm-local hour/minute directly gives the correct London booking time — this
is intentional, not a bug, and matches what the Matchi website itself displays.
Converting UTC → Europe/London directly would introduce a spurious 1-hour offset.
See `_ms_to_booking_time()` and the module docstring in `matchi/core/strategy.py`
for the full reasoning; don't "fix" this without re-reading it first.

An older `/book/findFacilities` endpoint (removed, see git history) embedded
genuinely Stockholm-local timestamps for a different reason and caused a real
1-hour lag bug — that's what prompted the switch to `/book/listSlots` in the
first place.

## Fixed July 2026: site-wide 403s from unbounded concurrency + no headers

Because Matchi bypasses `BaseCrawler`'s semaphore-bounded fetch loop, it used to
fire **all dates × all facilities concurrently with zero pacing** — up to ~100
simultaneous requests in one burst — and with **no headers at all** (not even a
`User-Agent`; httpx's bare default). Matchi's WAF was blocking every single
request outright as a result: every facility, every date, HTTP 403, for every
scheduled run. All Matchi rows in the `padel` table shared one stale
`last_refreshed` timestamp from whichever run last happened to get through.

Fixed by:
1. Adding the same browser-like headers Playtomic already used (a real mobile
   Safari `User-Agent`, `accept`, `accept-language`).
2. Wrapping each facility fetch in an `asyncio.Semaphore` sized to the existing
   `CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER` setting, threaded down from
   `MatchiPadelCrawler._crawl_async` through `crawl_date()` to
   `_fetch_facility_slots()`.

If Matchi starts 403ing again, check whether a code change re-introduced
unbounded concurrency here before assuming the WAF rules changed.

## Fixed July 2026: 2 specific facilities still 403 in a minority of runs

After the fix above, two facilities — `westhertssportsclub` and
`towerhillterrace` — kept getting HTTP 403 on **every date within a run**, but
only in ~4 of 10 consecutive scheduled runs, never partially. Root cause:
Matchi and Playtomic (see `docs/clubs/playtomic.md`) run in the same "Padel
Crawler Pipeline" job, so they share one GitHub Actions runner IP for the
whole run (fresh per job). Whether that run's IP happens to already be
blocklisted by Matchi's WAF for these two specific facilities is luck of the
draw - confirmed by the all-or-nothing-per-run pattern across 10 consecutive
runs' logs, not visible from isolated testing (which uses a different IP each
time).

Fixed the same way as Everyone Active's site-wide block
(`docs/clubs/everyone-active.md`), but as a **fallback**, not the default: on
HTTP 403 from the direct connection, `_fetch_facility_slots` retries against a
fresh `httpxAsyncClientWithProxyRotation()` connection (a fresh connection is a
fresh shot at a different proxy exit IP) up to 4 times before giving up. The
retry helper (`get_with_proxy_fallback_on_403` in `crawlers/anonymize/proxies.py`)
is shared with Playtomic's identical fix - both need "try direct first (fast,
works for the vast majority), escalate to proxy only on 403" in the exact same
shape. Any non-403 error (a genuine 5xx, a connection failure) is raised
immediately and not retried via proxy - retrying wouldn't help an actual
outage, only a blocklisted-IP situation.

## Known-unbookable venues (not crawler bugs)

Two facilities return **zero rows every run, deliberately** — confirmed by
fetching `/book/listSlots` directly and reading the HTML body:

- **Cumberland Lawn Tennis Club** (`cltc`, facility 2466): body reads
  `"Only members may book sessions."` — genuinely members-only, not publicly
  bookable.
- **St Paul's Cathedral Churchyard** (`stpaulscathedralchurchyard`, facility
  2995): body reads `"Not available for booking."`

Neither returns an HTTP error — both are 200s with a message div instead of
slot buttons, so `_parse_listslots_html()` correctly finds zero `btn-slot`
elements and returns an empty list. If either of these venues ever becomes
bookable, no code change is needed; they'll just start returning slots.

## Status (July 2026)

Confirmed live: 8 of 10 venues return data (the 2 above are genuinely
unbookable, not failures).

## Tennis (added August 2026)

`sport=1` is tennis (padel is `sport=5`). Confirmed valid two ways: the
sport-picker markup on real Matchi tennis venue booking pages explicitly
maps `value="1"` to the "Tennis" label, and behaviourally — `sport=1` and
`sport=2` both return the normal "not available" HTML fragment (a
recognised, processed sport ID with no slots), while `sport=99` (a control)
breaks the response format entirely rather than degrading gracefully.

`MatchiSlotFetcher` (`matchi/core/strategy.py`) now takes `sport_id`,
`category`, `facility_ids`, and `default_price` as constructor parameters
instead of hardcoding padel's values, so `MatchiTennisCrawler`
(`matchi/tennis/scraper.py`) reuses the same fetch/parse machinery with
`TENNIS_SPORT_ID`, `"Tennis"`, `TENNIS_SLUG_TO_FACILITY_ID` (a **separate**
map from padel's `SLUG_TO_FACILITY_ID` — Matchi facility IDs are
sport-specific per venue, not shared across sports at the same club).

**No confirmed populated slot response yet.** Two candidate venues were
tried live:

- **Frindsbury Tennis and Padel Club** (`facility=2865`, outside London —
  Rochester, Kent): `"Not available for booking."` — tennis isn't enabled
  for online booking at this venue, even though the sport ID itself is
  valid.
- **Putney Lawn Tennis Club** (`facility=2052`): `"Only members may book
  sessions."` — members-only, same shape as Cumberland LTC's padel listing
  above.

Both are wired in and will correctly return `[]` (not an error) via the same
zero-slots handling used for Matchi's known-unbookable padel venues — this
is expected, not a crawler bug. `default_price` is set to `"N/A"` rather
than reusing padel's hardcoded `"£55.00"`, since no real tennis pricing has
been observed live and that figure is a padel-specific guess, not something
parsed from the response either way.

**Coverage is the least proven of the four tennis providers built in this
pass** (ClubSpark, Better/GLL, Playtomic, Matchi) — needs a guest-bookable
Matchi tennis venue found before this can be confirmed end-to-end with real
data.

### Proxy note

Matchi's 403-fallback (`get_with_proxy_fallback_on_403`) is inherited
unchanged via the shared `MatchiSlotFetcher` — no new proxy code was needed
for tennis. `httpxAsyncClientWithProxyRotation()` now honours `USE_PROXIES`
globally (fixed earlier in the same session that added tennis), which
currently defaults `False` (Webshare free tier exhausted), so both Matchi
padel and Matchi tennis run fully unproxied by default. If a tennis venue
is 403-blocked directly, it will simply return no slots until proxy service
is restored — not a regression, an inherited, already-accepted constraint.
