# Tower Hamlets (Be Well)

4 venues, `https://be-well.org.uk/`. Badminton.
Code: `sportscanner/crawlers/parsers/towerhamlets/`.

## API shape

Base: `https://towerhamletscouncil.gladstonego.cloud/api/availability/V2/sessions?siteIds={siteId}&activityIDs={activityId}&webBookableOnly=true&dateFrom={ISO8601}&locationId=`

This is Gladstone's underlying booking-engine API directly (a different product
line from the `flow.onl` white-label seen elsewhere), and unlike every other
provider it requires an authenticated session: a `Jwt` cookie value sent as
`Cookie: Jwt={token}` plus `x-use-sso: 1`.

`dateFrom` matters more than it looks: **one request's response contains an
entire month of sessions**, not just the requested day. Both `run()` and
`coroutines()` in `towerhamlets/badminton/scraper.py` deliberately override
whatever `search_dates` the pipeline passes in and hard-code
`search_dates = [date.today()]` — asking for more dates would just mean
re-fetching and re-parsing the same monthly payload multiple times for no benefit.

## Auth: how the JWT is obtained, and a real fragility to know about

`towerhamlets/core/authenticate.py`'s `get_authorization_token()` launches a
headless Chromium via **`playwright.sync_api`**, navigates to
`towerhamletscouncil.gladstonego.cloud/book`, and reads the `Jwt` cookie Gladstone
sets after the page's own JS runs. `TowerHamletsCrawler.__init__` calls this
synchronously the moment the crawler is constructed, before any request goes out.

**This works today only because of the exact order `pipeline.py` calls it in.**
Playwright's sync API cannot run inside an already-active asyncio event loop —
it raises `Error: It looks like you are using Playwright Sync API inside the
asyncio loop. Please use the Async API instead.` if you try. `pipeline.py`
avoids this by constructing `TowerHamletsBadmintonScraperCoroutines(dates)` (which
transitively constructs `TowerHamletsCrawler()`) as a **plain function-argument
expression, evaluated before `asyncio.run(...)` starts** — so no event loop
exists yet at the moment the sync Playwright call runs:

```python
responses_for_reload = asyncio.run(
    SportscannerCrawlerBot(
        TowerHamletsBadmintonScraperCoroutines(dates)   # <- evaluated here, outside any loop
    )
)
```

If this ever gets refactored so that `coroutines()` (or `TowerHamletsCrawler()`)
is called from *inside* an `async def` function, or from inside a coroutine
that's already running under `asyncio.run`/`asyncio.gather` elsewhere, this
crawler will start hard-crashing with the error above on every run. This is not
hypothetical — it's exactly what happened when this crawler was probed directly
via `await coroutines(dates)` from an async test harness in July 2026 (see
`docs/clubs/README.md`'s "how this was compiled" note). It is **not currently
broken in production** — only fragile to a specific, plausible-looking refactor.

`authenticate.py` already imports `playwright.async_api.async_playwright` and
never uses it, which suggests an unfinished migration to the async API. Fully
switching to `async_playwright` (and awaiting it properly, likely via a lazy
async token fetch the first time a request needs it, since `_auth_token()` is
called synchronously by `BaseCrawler` today) would remove this landmine
permanently, but touches the shared `BaseCrawler._auth_token()` hook that every
other provider also implements (trivially, returning `None`), so treat that as a
deliberate follow-up, not a drive-by fix.

## Status (July 2026)

Confirmed live (called the same way `pipeline.py` calls it): all 4 venues return
data — 5,180 slots across a single day. No known issues, other than the fragility
above.
