# Sportscanner Backend - Claude Code Context

**Purpose**: This file provides context for Claude Code about the Sportscanner backend repository. It documents architecture, key components, common issues, and recent fixes to help future Claude interactions understand the codebase quickly.

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
- **BadmintonMasterTable**, **SquashMasterTable**, **PickleballMasterTable**: Court availability slots (production)
- **BadmintonStagingTable**, **SquashStagingTable**, **PickleballStagingTable**: Staging tables for zero-downtime updates
- **Notification**, **NotificationAck**: User notifications system
- **Critical**: `srid` column must be populated with `ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)`
- **Table Swapping**: `swap_tables()` function swaps staging → master for zero-downtime updates

### 3. Crawler System (`sportscanner/crawlers/parsers/`)
Strategy pattern implementation:
- **AbstractRequestStrategy**: Generates API requests for a venue/date
- **AbstractResponseParserStrategy**: Parses API responses to `UnifiedParserSchema`
- **AbstractAsyncTaskCreationStrategy**: Creates async tasks for concurrent fetching
- **BaseCrawler**: Orchestrates the crawling process

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

## Provider-Specific Variations
### Better/GLL (`better/`)
- **Activity IDs**: `badminton-40min`, `badminton-60min`, `squash-court-40min`, `pickleball-40mins`, `pickleball-60mins`
- **v2 Endpoints**: Woolwich Waves uses `/v2` suffix: `badminton-40min/v2`
- **Lee Valley**: Special pickleball activity ID: `pickleball-60mins-court`
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