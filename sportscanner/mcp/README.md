# SportScanner MCP Server

This MCP server exposes SportScanner API routes as typed, documented tools so
agents can call SportScanner safely and consistently.

## What Is Exposed

The server currently wraps these API groups:

- Search (`/search/*`)
- Venues (`/venues/*`)
- Geolocation (`/geolocation/*`)
- Health (`/health/scrapers`)
- User profile (`/user/*`)
- Notifications (`/notifications/*`)
- Root metadata (`/`)

## Run

```bash
cd app-crawlers
python -m sportscanner.mcp.server
```

Default transport and port:

- Transport: `http`
- Port: `8080`

## Environment

- `SPORTSCANNER_MCP_API_BASE_URL` (optional):
  - Overrides which SportScanner API instance is called by tools.
  - Defaults to `settings.API_BASE_URL` from backend config.
  - Example: `http://localhost:8000` for local API development.

- `SPORTSCANNER_MCP_SERVER_URL` (optional):
  - Used by the Google ADK chat agent when connecting to this MCP server.
  - Defaults to `http://127.0.0.1:8000/mcp` when running the API locally.

- `OPENAI_BASE_URL` (optional):
  - OpenAI-compatible base URL for the chat model (for example Azure AI
    Foundry OpenAI-compatible endpoints).
  - Example:
    `https://orca-resource.services.ai.azure.com/openai/v1`

- `PHOENIX_API_KEY` + `PHOENIX_COLLECTOR_ENDPOINT` (optional):
  - Enable Phoenix observability export for backend API and agent traces.
  - When both are set, SportScanner calls `phoenix.otel.register(...)` at
    FastAPI startup.
  - Optional:
    - `PHOENIX_CLIENT_HEADERS` (for older Phoenix Cloud tenants requiring
      explicit header style auth, e.g. `api_key=<key>`)
    - `PHOENIX_PROJECT_NAME` (default: `sportscanner-backend`)
    - `PHOENIX_AUTO_INSTRUMENT` (default: `True`)

## Auth Behavior

Tools that call authenticated endpoints accept an `authorization` parameter.
This value is forwarded verbatim as the HTTP `Authorization` header.

Current backend behavior expects the Kinde refresh token value currently used by
existing SportScanner clients.

## Tool Reference

### Root

1. `sportscanner_api_root`
- Endpoint: `GET /`
- Description: Returns API metadata (`message`, `version`, top-level actions).
- Parameters: none

### Search

1. `sportscanner_search_sport_availability`
- Endpoint: `POST /search/{sport}?date=YYYY-MM-DD`
- Description: Returns grouped availability results for nearby venues.
- Parameters:
  - `sport`: `badminton | squash | pickleball | padel`
  - `search_date`: ISO date string
  - `filters`:
    - `postcode` (required)
    - `radius` (miles, default `10.0`)
    - `timeRange.starting` and `timeRange.ending` (required)
    - `sortBy`: `distance | price` (default `distance`)
    - `analytics`:
      - `consecutiveSlots` (optional)
      - `searchUserPreferredLocations` (default `false`)
      - `specifiedVenues` (optional list of composite keys)

2. `sportscanner_search_single_venue_availability`
- Endpoint: `POST /search/{sport}/{composite_key}?date=YYYY-MM-DD`
- Description: Returns raw slot rows for one venue and sport on one date.
- Parameters:
  - `sport`: `badminton | squash | pickleball | padel`
  - `composite_key`
  - `search_date`

### Venues

1. `sportscanner_list_venues`
- Endpoint: `GET /venues/`
- Description: Returns all venues (optionally limited).
- Parameters:
  - `limit` (optional integer)

2. `sportscanner_list_venues_by_sport`
- Endpoint: `GET /venues/sports/{sport}`
- Description: Returns venues offering one sport.
- Parameters:
  - `sport`: `badminton | squash | pickleball | padel`
  - `limit` (optional integer)

3. `sportscanner_find_venues_near_postcode`
- Endpoint: `GET /venues/near?postcode=&distance=`
- Description: Returns venues near a postcode within a radius.
- Parameters:
  - `postcode`
  - `distance_miles` (default `10.0`)

4. `sportscanner_get_venue_by_composite_key`
- Endpoint: `GET /venues/{composite_key}`
- Description: Returns one venue profile by composite key.
- Parameters:
  - `composite_key`

### Geolocation

1. `sportscanner_validate_postcode`
- Endpoint: `GET /geolocation/validate-postcode?postcode=`
- Description: Validates a raw postcode.
- Parameters:
  - `postcode`

2. `sportscanner_get_postcode_metadata`
- Endpoint: `GET /geolocation/metadata-postcode?postcode=`
- Description: Validates postcode and returns metadata payload.
- Parameters:
  - `postcode`

3. `sportscanner_autocomplete_postcode`
- Endpoint: `GET /geolocation/autocomplete?q=`
- Description: Returns postcode suggestions.
- Parameters:
  - `query`

4. `sportscanner_reverse_geocode_to_postcode`
- Endpoint: `GET /geolocation/reverse?lat=&lon=`
- Description: Returns nearest postcode for coordinates.
- Parameters:
  - `latitude`
  - `longitude`

5. `sportscanner_resolve_location_query`
- Endpoint: `GET /geolocation/resolve-location?q=`
- Description:
  Resolves flexible location text to a full postcode and coordinates.
  Supports:
  - full postcode (for example `SW1A 1AA`)
  - postcode outcode/district (for example `E14`)
  - London place name (for example `Paddington`)
- Parameters:
  - `query`

6. `sportscanner_find_venues_near_location_query`
- Endpoint flow:
  - `GET /geolocation/resolve-location?q=`
  - then `GET /venues/near?postcode=&distance=`
- Description:
  Convenience tool that resolves a partial location query first, then returns
  nearby venues in one call.
  If the query cannot be resolved, it returns a structured unresolved payload
  (`resolved=false`, `message`, empty `venues`) instead of throwing.
- Parameters:
  - `location_query`
  - `distance_miles` (default `10.0`)

### Health

1. `sportscanner_get_scrapers_health`
- Endpoint: `GET /health/scrapers?sports={sport}`
- Description: Returns refresh recency per venue/date and computed health.
- Parameters:
  - `sport`: `badminton | squash | pickleball | padel`

### User

1. `sportscanner_get_user_profile`
- Endpoint: `GET /user/`
- Description: Returns authenticated user profile.
- Parameters:
  - `authorization`

2. `sportscanner_register_user`
- Endpoint: `POST /user/`
- Description: Registers authenticated user on first login.
- Parameters:
  - `authorization`

3. `sportscanner_update_user_profile`
- Endpoint: `PATCH /user/`
- Description: Updates onboarding and/or preferences.
- Parameters:
  - `authorization`
  - `update` object:
    - `onboarding` (optional boolean)
    - `preferences` (optional key/value map)
  - Validation: at least one of `onboarding` or non-empty `preferences` required.

### Notifications

1. `sportscanner_list_notifications`
- Endpoint: `GET /notifications/`
- Description: Returns active notifications for current user.
- Parameters:
  - `authorization`

2. `sportscanner_acknowledge_notification`
- Endpoint: `POST /notifications/{notification_id}/acknowledge`
- Description: Marks notification as acknowledged for current user.
- Parameters:
  - `notification_id`
  - `authorization`

3. `sportscanner_create_notification`
- Endpoint: `POST /notifications/admin`
- Description: Creates a global notification.
- Parameters:
  - `authorization`
  - `payload`:
    - `title` (required)
    - `message` (required)
    - `active` (default `true`)

4. `sportscanner_update_notification`
- Endpoint: `PATCH /notifications/admin/{notification_id}`
- Description: Partially updates an existing notification.
- Parameters:
  - `notification_id`
  - `authorization`
  - `payload`:
    - `title` (optional)
    - `message` (optional)
    - `active` (optional)
  - Validation: at least one payload field must be provided.

## Testing

Run MCP-specific tests:

```bash
cd app-crawlers
pytest tests/mcp -v
```

Coverage includes:

- Tool registration completeness
- Tool schema/description metadata checks
- Endpoint mapping and request-shape assertions
- Input validation behavior
- Error normalization behavior in HTTP wrapper

## Google ADK Agent Endpoint

The backend also exposes a chat endpoint powered by Google ADK that consumes these
MCP tools:

- Route: `POST /chat/agent`
- Request body:
  - `messages`: ordered chat transcript (`role`, `content`)
- Optional header:
  - `Authorization: Bearer <kinde_refresh_token>` for profile-aware answers
    (for example resolving "near me" via saved postcode).
- Required env:
  - `OPENAI_API_KEY` (or `AZURE_OPENAI_API_KEY`)
- Optional env:
  - `SPORTSCANNER_AGENT_MODEL` (default: `openai/gpt-4.1-mini`)
    - Supports ADK-compatible model names (for example `gpt-4.1-mini` or
      `openai/gpt-4.1-mini` when LiteLLM is available).
    - For OpenAI-compatible custom deployments, use provider-prefixed models
      like `openai/Kimi-K2.6`.

The endpoint returns:

- `reply`: assistant answer text
- `used_tools`: MCP tools that were invoked
- `model`: active chat model
