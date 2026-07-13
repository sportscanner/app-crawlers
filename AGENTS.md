# Sportscanner Backend - Agent Context

**Purpose**: This file provides context for AI coding agents (Claude Code, Codex, or others reading the `AGENTS.md` convention) working in the Sportscanner backend repository. It documents architecture, key components, common issues, and recent fixes so an agent picking this up cold can get productive quickly.

For per-provider detail (API shape, auth, known quirks, live status), see `docs/clubs/` — one file per booking provider, plus a README index. That folder is the authoritative, kept-current source; the "Provider-Specific Variations" section below is a lighter, older summary and may lag behind it.

## Documentation Style

- No em dashes in any documentation (this file, `docs/`, `README.md`, `ARCHITECTURE.md`). Use a comma, a colon, or a full stop instead.
- No emojis in documentation.
- Keep language crisp. Document high-level architecture and design decisions, not line-by-line explanations of what code does.

## Project Overview
Sportscanner is a court availability aggregator for racket sports (badminton, squash, pickleball) across London. It consists of:
- **Crawlers**: Python scripts that fetch court availability from various booking websites
- **API**: FastAPI backend that serves availability data to the Next.js frontend
- **Database**: PostgreSQL with geospatial support for venue distance calculations

## Architecture
```
├── sportscanner/
│   ├── api/                    # FastAPI endpoints
│   ├── crawlers/               # Web crawlers and parsers
│   ├── storage/                # Database models and operations
│   ├── schemas.py              # Pydantic schemas
│   ├── variables.py            # Environment configuration
│   └── venues.json             # Venue configuration
├── scripts/                    # SQL scripts
└── reports/                   # Crawler reports
```

## Key Components

### 1. Venue Configuration (`sportscanner/venues.json`)
- Contains all sports venues organized by provider (Better, Everyone Active, etc.)
- Each venue has: name, slug, location, supported sports
- **Composite Key**: MD5 hash of `organisation_website|slug` (first 8 chars)
- Used by `load_sports_centre_mappings()` to populate `SportsVenue` table

### 2. Database Schema (`sportscanner/storage/postgres/`)
- **SportsVenue**: Venue metadata with geospatial `srid` column for distance queries
- **BadmintonMasterTable**, **SquashMasterTable**, **PickleballMasterTable**, **PadelMasterTable**: Court availability slots, written directly (no staging/swap tables exist in the current schema)
- **Notification**, **NotificationAck**: User notifications system
- **Critical**: `srid` column must be populated with `ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)`
- Writes go through `insert_records_to_table()` (upsert on `uid`, stale rows marked `spaces=0` via SQL `UPDATE`) or `truncate_by_composite_key_and_reload()` (delete + reinsert by `composite_key`, used by TowerHamlets). See `docs/database.md` for the write-path rationale.

### 3. Crawler System (`sportscanner/crawlers/parsers/`)
Strategy pattern implementation. A provider supplies only two strategies:
- **AbstractRequestStrategy**: Generates API requests for a venue/date
- **AbstractResponseParserStrategy**: Parses API responses to `UnifiedParserSchema`
- **BaseCrawler** (`core/interfaces.py`): Owns the shared fetch → validate → parse →
  error-handling loop, per-provider concurrency cap, and fallback-URL retries.
  Providers whose API differs override small hooks instead of the loop:
  `_auth_token` (session token), `_extract_content` (unwrap the slot payload),
  `_is_empty_content`, `_on_empty_response`. Better/GLL-style providers (Better,
  ActiveLambeth, Haringey) share the `BetterStyleCrawler` subclass; Playtomic/Matchi
  override `ScraperCoroutines` (their APIs iterate by date/tenant, not per-venue URL).
  (The old per-provider `AbstractAsyncTaskCreationStrategy` was removed — the fetch
  loop now lives once in `BaseCrawler`.)

#### Provider Structure:
```
better/
  ├── badminton/scraper.py    # BetterLeisureBadmintonRequestStrategy
  ├── squash/scraper.py
  ├── pickleball/scraper.py
  └── core/strategy.py        # BetterLeisureResponseParserStrategy
```

#### Unified Schema:
```python
class UnifiedParserSchema:
    category: str              # "Badminton", "Squash", "Pickleball"
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int                # 0 = unavailable, >0 = available
    composite_key: str         # Foreign key to SportsVenue
    last_refreshed: datetime
    booking_url: Optional[str]
```

### 4. API Endpoints (`sportscanner/api/routers/`)
- **GET /search/{sport}**: Main search endpoint with postcode/distance filtering
- **GET /venues/near**: Find venues within radius of postcode
- **GET /venues/**: List all venues
- **POST /notifications/**: User notification system

#### Search Flow:
1. User provides postcode → geocode via Postcodes.io API
2. Find venues within radius using `ST_DWithin(srid, point, distance)`
3. Query slots with `spaces > 0` and future `starting_time`
4. Group slots by composite_key/date using `group_slots_by_attributes()`
5. Format for UI using `sort_and_format_grouped_slots_for_ui()`

#### UI Formatting (`sportscanner/storage/postgres/dataset_transform.py`)
- `group_slots_by_attributes()`: Groups slots by composite_key and date
- `sort_and_format_grouped_slots_for_ui()`: Creates UI-ready JSON with venue metadata
- `generate_venue_lookup()`: Builds venue metadata dictionary
- **Healthcheck**: Marks data as "deprecated" if older than 35 minutes

### 5. Database Operations (`sportscanner/storage/postgres/database.py`)

#### Key Functions:
- `insert_records_to_table()`: Bulk upsert with deduplication (prefers slots with `spaces > 0`)
- `load_sports_centre_mappings()`: Loads venues from JSON, **must populate `srid`**
- `get_all_rows()`: Generic query execution

#### Deduplication Logic:
- 40min/60min API calls may return same slots
- Prefer slots with `spaces > 0` over `spaces = 0` (fallback from empty responses)

## Common Issues & Fixes

### 1. Venues Not Appearing in Search Results
**Problem**: `srid` column is `NULL` in `SportsVenue` table
**Solution**: Ensure `load_sports_centre_mappings()` includes:
```python
session.execute(text("UPDATE sportsvenue SET srid = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) WHERE srid IS NULL"))
```

### 2. Stale Slots Showing Old Availability
**Problem**: Slots removed from API still show old availability in DB
**Solution**: `insert_records_to_table()` marks missing slots as `spaces = 0`

### 3. Duplicate Slots from 40min/60min APIs
**Problem**: Both API versions return same time slot
**Solution**: Deduplication prefers slots with `spaces > 0`

### 4. Distance Queries Returning No Results
**Check**:
1. `srid` column populated for all venues
2. Postcodes.io API responding correctly
3. Distance in meters: `miles * 1609.344`

## Makefile Commands

```bash
make setup              # Install dependencies (pip + playwright + editable install)
make dev-api-server     # Run FastAPI dev server on localhost:8000 (uses .dev.env)
make test               # Run pytest
make format             # Run isort + black formatters
make freeze             # Regenerate requirements.txt via pipreqs
make reset-database-tables  # Truncate DB tables and reset metadata

# Docker (production)
make build-docker-image         # Build linux/amd64 image
make push-image-to-repository   # Push to GHCR
make api-server-container       # Run API server container (prod, port 8000)
make crawler-pipeline-container # Run crawler pipeline in container (prod)
```

**Environment files**: `.dev.env` for local dev, `.env` for production (selected by `ENV=prod`).

## MCP Server

An MCP (Model Context Protocol) server lives in `sportscanner/mcp/`.
- Runs via `FastMCP` on HTTP transport, port 8080
- Exposes geolocation tools for venue search
- Start with: `python -m sportscanner.mcp.server`

## Development Workflow

### Running Crawlers
```python
from sportscanner.crawlers.parsers.better.badminton.scraper import BetterLeisureCrawler
crawler = BetterLeisureCrawler()
results = crawler.crawl(venues, dates)
```

### Database Initialization
```python
from sportscanner.storage.postgres.database import initialize_db_and_tables
initialize_db_and_tables(engine)  # Creates tables, loads venues, populates srid
```

### Testing Search
```python
# Check if venue appears in distance query
composite_key = "c3a8df88"  # Finsbury Leisure Centre
venue = get_venue_by_composite_key(composite_key)
# Verify srid is not NULL
```

## Environment Configuration (`variables.py`)
- `DB_CONNECTION_STRING`: PostgreSQL connection
- `API_BASE_URL`: Internal API URL for self-referencing
- `USE_PROXIES`, `ROTATING_PROXY_ENDPOINT`: Crawler proxy settings
- `KINDE_DOMAIN`, `KINDE_CLIENT_ID`: Authentication

## Git & Deployment
- **Main branch**: `main` (production)
- **Feature branches**: `feature/*`, `fix/*`
- **CI/CD**: GitHub Actions for crawlers and tests
- **Recent fix**: `srid` population in `load_sports_centre_mappings()`

## Important Notes
1. **Composite Keys**: Generated via `generate_composite_key([org_website, slug])`
2. **Geospatial**: All distance calculations use PostGIS `srid` column
3. **Slot Availability**: `spaces = 0` means unavailable (stale or booked)
4. **Provider Variations**: Some venues use `/v2` endpoints (e.g., Woolwich Waves)
5. **Error Handling**: Parser error messages should use `slot.starts_at.format_24_hour` not `slot['Time']`

## Adding a New Venue: End-to-End Checklist

Distilled from the venues added July 2026 (UEL SportsDock, Places Leisure) and
every fix made to existing providers that same month. Work through these in
order — later steps assume earlier ones are done.

### 1. Research the booking platform before writing any code
- Find the venue's actual booking flow (not just its info page) and identify
  the underlying vendor. Check known platforms first before assuming it's
  bespoke: **Better/GLL** (`better-admin.org.uk`), **Gladstone** (either
  `{tenant}.gladstonego.cloud` directly, or white-labelled at `flow.onl`),
  **Leisure Hub / "LhWeb"** (`.../LhWeb/en/api/Sites/{id}/Timetables/ActivityBookings`,
  used by CitySport, UEL SportsDock), **Matchi**, **Playtomic**. Reusing an
  already-integrated platform's request/parse logic is far cheaper than a new
  scraper — see `docs/clubs/README.md`'s "how this was compiled" note on the
  `/categories/{sport}` discovery trick for Better/GLL specifically.
- Determine whether availability is genuinely public/anonymous (every
  provider integrated so far is) or requires a real user login to see
  anything. If it's login-gated for viewing (not just booking), stop and
  flag it — that's a scope decision, not something to route around.
- Test for a TLS-fingerprinting WAF: try a plain `httpx`/`curl` request first;
  if it's blocked (connection reset mid-handshake, or a bare `curl` succeeds
  but Python's `ssl` module doesn't), the site needs `curl_cffi` with
  `impersonate="chrome124"` instead (see `docs/clubs/citysport.md`).
- Confirm live data with an actual slot response before writing the scraper,
  not just "the site claims to offer this sport."

### 2. Decide: standard `BaseCrawler` loop, or bypass?
- If the API is one request per `(venue, date)`, use the standard
  `AbstractRequestStrategy` + `AbstractResponseParserStrategy` pair — see
  `sportscanner/crawlers/parsers/uelsportsdock/` as the simplest example.
- If it doesn't fit that shape (returns all venues per date like
  Matchi/Playtomic, needs a two-phase fetch like Places Leisure, or needs a
  different HTTP transport like CitySport's `curl_cffi`), override
  `ScraperCoroutines` directly and implement your own fetch loop. This is the
  established, preferred pattern in this codebase — extend `BaseCrawler`,
  don't fork it. See any of `matchi/`, `playtomic/`, `citysports/`,
  `placesleisure/` for worked examples of *why* each one needed to bypass.
- If you add unbounded concurrency in a bypass (no `asyncio.Semaphore`), you
  will get the provider's WAF blocking every request — this happened to
  Matchi and Playtomic. Always cap concurrency with
  `asyncio.Semaphore(settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER)`.

### 3. Write the provider module
- Follow the existing folder structure: `{provider}/core/schema.py` (response
  shape), `{provider}/core/strategy.py` (request + parse logic), and one
  `{provider}/{sport}/scraper.py` per sport offered, each exposing a
  `coroutines(search_dates)` entry point.
- Reuse an existing schema class (e.g. `CitySportsResponseSchema`) if you
  confirmed the same platform — don't reinvent field-for-field-identical
  Pydantic models.

### 4. Wire it up
- Add venue(s) to `sportscanner/venues.json` under a new or existing
  organisation block. Compute `composite_key` yourself to sanity-check it:
  `generate_composite_key([organisation_website, slug])` (MD5 of
  `f"{organisation_website}|{slug}"`, first 8 chars — see
  `sportscanner/storage/postgres/utils.py`).
- Import the new `coroutines` function and add it to the relevant
  `*_scraping_pipeline()` call(s) in `sportscanner/crawlers/pipeline.py`.

### 5. Get the venue into the production database
- **Do not** run `load_sports_centre_mappings()` / `initialize_db_and_tables()`
  against prod — it uses raw `session.add()` with no upsert handling and is
  not safe against a non-empty `sportsvenue` table.
- Instead, `INSERT` the venue row(s) directly into prod `sportsvenue`,
  matching the exact `composite_key` your `venues.json` entry computes to,
  including `srid = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)`.

### 6. Verify live, twice
- **Locally first**: run the real `coroutines()` entry point directly
  (`ENV=prod python3 -c "..."`) against the production database — `.env` at
  the repo root has real credentials, this is read-only-safe and standard
  practice in this codebase. Confirm a realistic slot count and genuine mixed
  availability (not all-zero, not all-full).
- **Then check a real GitHub Actions run** after deploying — local
  verification is not sufficient on its own. Multiple providers this session
  worked perfectly from a local/dev connection but failed from GitHub
  Actions' runner IPs specifically: CitySport (TLS fingerprint block, fixed
  with `curl_cffi`), Everyone Active (soft IP block, fixed by routing through
  the rotating proxy), UEL SportsDock (`ReadTimeout` from GH Actions only,
  same proxy fix), and a handful of Matchi/Playtomic venues (403 on ~40-70%
  of runs, IP-dependent). Always pull the actual job log from the next
  scheduled run and grep for your new provider before calling it done — see
  `docs/clubs/everyone-active.md` and `docs/clubs/citysport.md` for how this
  class of bug was diagnosed each time.
- If GitHub Actions fails where local succeeds, don't guess — check for a
  clean HTTP error (403 → try `get_with_proxy_fallback_on_403()` in
  `crawlers/anonymize/proxies.py`, already used by Matchi/Playtomic) versus a
  silent hang/timeout (→ the venue needs to route through the proxy directly
  from the first attempt, like Everyone Active and UEL SportsDock do — a 403
  fallback doesn't trigger on a timeout, there's no clean error to catch).
- Re-run a couple of *other* already-working providers after your change to
  confirm you didn't regress shared code (`core/interfaces.py`,
  `crawlers/anonymize/proxies.py`).

### 7. Document it
- Write `docs/clubs/{provider}.md` following the existing files' structure:
  API shape, auth, quirks/gotchas, known limitations, live status with a
  date. Add a row to `docs/clubs/README.md`'s index table.
- If you discovered something generically reusable (a new diagnostic
  technique, a new failure class), fold it into `docs/crawlers.md` too.

### 8. Frontend
- Add a `VENUE_DATA` entry in `app-frontend/lib/venue-data.ts`, keyed by the
  same `composite_key`: `organisation`, `venue_name`, `address`, and
  `transport` (nearest stations, walk time, lines). Search results and
  availability come from the live backend API regardless of this file — this
  only powers the venue detail page's "Get directions" panel and club info.
  If it's missing, that panel silently renders empty rather than erroring.
- **Push frontend changes to `dev` (beta.sportscanner.co.uk) first.** Only
  push to `main` (prod) when the user explicitly confirms — this is a standing
  rule, not a one-off. If asked to promote a specific fix to `main` without
  promoting everything on `dev`, cherry-pick that one commit rather than
  fast-forwarding `main` to `dev`'s tip (which would pull in unrelated
  in-progress work). After pushing to `main`, cherry-pick the same commit
  onto `dev` too so the branches don't diverge.

## Provider-Specific Variations
### Better/GLL (`better/`)
- **Activity-slug config lives in `better/core/activities.py`** — a declarative registry of
  per-sport `(primary, fallback)` activity-slug pairs plus per-venue overrides. Add a
  venue quirk there (one data entry), not as an `if` branch in the request builder.
- **v1/v2 rollout**: Better is mid-migrating to a `/v2` times endpoint per venue/activity;
  each pair tries the primary slug then falls back to the other on an HTTP error. Squash's
  slug name also changes on v2 (`squash-court-40min` → `squash-40min`).
- **Pickleball's slug spelling changes between v1 and v2**, not just the version suffix:
  v1 is plural, no version (`pickleball-40mins`); v2 dropped the "s" (`pickleball-40min/v2`).
  Confirmed v1-only (legacy) venues: `score-leisure-centre`, `barking-sporthouse-and-gym`,
  `waltham-forest-feel-good-centre`, `walthamstow-leisure-centre`, `leytonstone-leisure-centre`.
  The other ~17 of 22 pickleball venues (including `lee-valley-velopark`,
  `woolwich-waves-leisure-centre`, `the-plumstead-centre`) are v2-only — v1 answers with
  Better's generic "date should be within the valid days you are able to view" 422 (not a
  clean 404) since the plural activity no longer exists for them, so `activity_slug_pairs`
  uses plural/v1 as primary and singular/v2 as fallback to cover both groups in one config.
  Getting the fallback's pluralization wrong here previously left ~17 venues with silently
  zero pickleball rows despite genuinely having availability — check both spellings before
  assuming a venue has none.
- **Per-venue overrides**: e.g. `shene-sports-and-fitness-centre` (single `badminton-court`
  activity).
- **API Response Format**: slots under a top-level `data` key; sometimes dict with numeric keys, sometimes list
- **API Response Format**: Sometimes returns dict with numeric keys, sometimes list

### Everyone Active (`everyoneactive/`)
- Uses XML-based booking system
- Different parsing strategy required

### Tower Hamlets (`towerhamlets/`)
- Requires authentication token
- `authenticate.py` handles session management

### CitySports (`citysports/`)
- University-based booking system
- Simple JSON API structure

## Quick Reference
- **Finsbury Leisure Centre**: `composite_key = "c3a8df88"`
- **Better API**: `https://better-admin.org.uk/api/activities/venue/{slug}/activity/{activityId}/times`
- **Database Tables**: `badminton`, `squash`, `pickleball`, `sportsvenue`
- **Search Filter**: `spaces > 0` and `starting_time > NOW()`

## Pipeline & Scheduling (`sportscanner/crawlers/pipeline.py`)
- Orchestrates concurrent crawling across all providers
- `badminton_scraping_pipeline()`, `squash_scraping_pipeline()`, `pickleball_scraping_pipeline()`
- Calls provider-specific `coroutines()` functions for async fetching
- Uses `insert_records_to_table()` for bulk database updates
- **GitHub Actions**: Scheduled crawler jobs in `.github/workflows/`

### MCP Integration (`sportscanner/mcp/`)
- Model Context Protocol server for Claude integration
- Provides geolocation tools for venue search
- Used by Claude Code for intelligent search assistance

### Proxy System (`sportscanner/crawlers/anonymize/`)
- Rotating proxy support for crawlers
- `httpxAsyncClient` wrapper with proxy configuration
- Prevents IP blocking during frequent API requests

### Logging (`sportscanner/logger.py`)
- Loguru-based logging with configurable levels
- Standardized across all modules
- Levels: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL

### Analytics (`sportscanner/analytics/`)
- `consecutive.py`: Advanced filtering for consecutive time slots
- Used in search criteria for finding back-to-back bookings

### Recent Critical Fixes
1. **Missing `srid` column**: Added `UPDATE sportsvenue SET srid = ST_SetSRID(...)` in `load_sports_centre_mappings()`
2. **Parser error message**: Fixed `slot['Time']` → `slot.starts_at.format_24_hour` in `BetterLeisureResponseParserStrategy`
3. **Venue name typos**: Fixed in `venues.json` (Queensbridge, Leytonstone)
4. **Deduplication**: Prefer slots with `spaces > 0` over `spaces = 0` in `insert_records_to_table()`