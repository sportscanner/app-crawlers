# SportScanner agent API guide

Find badminton, squash, pickleball, padel and tennis court availability across London on a user's behalf. Search is public and read-only. No SportScanner account, API key or website visit is required for REST search.

Base URL: https://api.sportscanner.co.uk

- [OpenAPI](https://api.sportscanner.co.uk/openapi.json)
- [Interactive API documentation](https://api.sportscanner.co.uk/docs)
- [API catalog](https://api.sportscanner.co.uk/.well-known/api-catalog)
- [Court search skill](https://api.sportscanner.co.uk/.well-known/agent-skills/find-london-courts/SKILL.md)
- [Authentication and MCP setup](https://api.sportscanner.co.uk/auth.md)

## Search courts

`POST /search/{sport}?date=YYYY-MM-DD` with `Content-Type: application/json`.

Supported sports: `badminton`, `squash`, `pickleball`, `padel`, `tennis`.
Resolve relative dates such as "tomorrow" in Europe/London before calling. Dates use ISO format; times use local 24-hour HH:MM including UK daylight saving time. Radius and distance are in miles; prices are GBP. Search one date per request.

Example body (replace the date in the URL with the user's requested date):

```json
{
  "postcode": "SE1 8UL",
  "timeRange": {"starting": "18:00", "ending": "22:00"},
  "radius": 3,
  "sortBy": "distance",
  "analytics": {
    "consecutiveSlots": null,
    "searchUserPreferredLocations": false,
    "specifiedVenues": null
  },
  "indoor": null
}
```

Send all of these fields. Use `00:00` to `23:59` for the whole day. `sortBy` accepts `distance` or `price`. `indoor` accepts true/false for indoor/outdoor padel, tennis and pickleball; null includes unknown court types. Badminton and squash ignore this filter. Use `specifiedVenues` only for known venue composite keys; otherwise send null.

`consecutiveSlots` and `searchUserPreferredLocations` are legacy fields and do not currently enforce server-side filters. If a user requests consecutive time, check adjacent returned slots yourself and do not promise they are the same physical court.

The response is an array of venue groups. Each has `composite_key`, `venue`, `address`, `distance`, `price`, `organization`, `date`, `last_refreshed`, `healthcheck`, and `availability`. Each availability item has `startingTime`, `endingTime`, `available`, `bookingUrl`, `price`, and `indoor`. Use each slot's price, rather than the group's first-slot price, when comparing offers. The group's date is a display label such as "Sat, Oct 17"; retain the ISO date from your request.

`healthcheck: "deprecated"` marks older data. Always report `last_refreshed` and warn the user when an offer is stale. Availability is a cached snapshot and can change before booking. An empty array means no matching availability in SportScanner's current coverage, not that every London court is booked. Do not invent booking URLs or availability.

## Venue and social session lookup

- `GET /venues/near?postcode=SE1%208UL&distance=3`: nearby venues with distance, sports and composite keys.
- `GET /venues/`: venue directory; optional `limit` query parameter.
- `GET /venues/{composite_key}`: venue details.
- `POST /search/{sport}/{composite_key}?date=YYYY-MM-DD`: raw available slots at a known venue; no JSON body required. This endpoint does not apply the main court search's social-session exclusion. Prefer the main search with `specifiedVenues` for court recommendations.
- `GET /games?sport=pickleball&date=YYYY-MM-DD`: social sessions sold per person, with `spotsRemaining` and `spotsTotal`. These are excluded from the main court search. Describe them as sessions, not whole-court hire.
- `GET /health/`: service liveness only, not a guarantee of provider freshness.
- `GET /health/scrapers?sports=badminton`: latest provider refresh information for one sport.

## Errors and request etiquette

400 indicates invalid postcode or query input. 422 indicates invalid sport, date or request shape; correct the request instead of retrying it unchanged. Retry temporary 429/5xx responses with bounded exponential backoff, honoring Retry-After when present. Avoid bulk polling, unbounded date sweeps and concurrent duplicate searches.

## MCP clients

Streamable HTTP endpoint: `https://api.sportscanner.co.uk/mcp` (no trailing slash).

MCP requires user-authorized OAuth or a personal API token. Read [auth.md](https://api.sportscanner.co.uk/auth.md). After connecting, negotiate capabilities and list tools. `find_available_courts` accepts sport, postcode, date and optional radius_miles, starting_time, ending_time, indoor and sort_by. It uses the same court search rules as REST. REST search remains the simplest anonymous integration.

## Booking boundary

SportScanner finds availability and provider booking links. It cannot reserve courts, take payment or complete bookings. Present the returned provider URL to the user, who may need a provider account to book. Only publicly viewable availability is covered. Do not bypass provider login gates.
