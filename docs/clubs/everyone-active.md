# Everyone Active

12 venues, `https://www.everyoneactive.com/`. Badminton.
Code: `sportscanner/crawlers/parsers/everyoneactive/`.

## API shape

Per-venue hardcoded `activityId` strings (e.g. `queen-mother-sports-centre` ->
`"155BADMINTON1"`, `reynolds-sports-centre` -> `"119BADM050SH001"`) in a dict
literal in `EveryoneActiveBadmintonRequestStrategy.generate_request_details`.
These IDs don't follow a predictable pattern across venues (different
prefixes/suffixes per centre), so there's no slug-derivation logic to maintain —
each new venue just needs its ID looked up once and added to the dict, the same
pattern as Matchi's `SLUG_TO_FACILITY_ID` and Playtomic's `SLUG_TO_TENANT_ID`.

Dates are passed as UTC timestamp ranges (`get_utc_timestamps(fetch_date)` in
`everyoneactive/core/utils.py`), not a plain date string like the Gladstone-family
providers use.

## Status (July 2026)

Confirmed live: all 12 venues return data (24/24 requests across a 2-day probe).
No known issues.

## Adding a new venue

Look up the venue's `activityId` from the network tab on
`everyoneactive.com`'s own booking flow for that centre, then add
`"venue-slug": "theActivityId"` to the dict. There's no discovery API for this
one (unlike Better/GLL's `/categories` endpoint) — it has to be read off the live
site.
