# Decathlon

1 venue (Decathlon Surrey Quays), `https://decathlon.co.uk/`. Pickleball.
Code: `sportscanner/crawlers/parsers/decathlon/`.

## API shape

Base: `https://api-eu.decathlon.net/activities/v2/activities/{activityId}/timeslots?timeslotStatus=PUBLISHED&excludeFull=false&startDate={ISO8601}&sort[by]=startDate&sort[order]=asc&pagination[from]=0&pagination[limit]=100`

Decathlon's own activity-booking platform (unrelated to Gladstone). Two hardcoded
`activityId`s cover the two pricing tiers, both queried per date:
`"6838177"` (off-peak, £12) and `"7473556"` (peak, £20). `startDate` is a fixed
"now" timestamp per run rather than per requested date — the endpoint's own
pagination/date-range params do the filtering, not our date loop.

Requires an `x-api-key` header (`666565be-422c-4b54-8138-682de3b95aee`) — again a
static key baked into source, looks like a public mobile/web app key rather than
an account secret.

## Status (July 2026)

Confirmed live: the venue returns data (141 available / 207 total slots checked).
No known issues.

## Adding a new venue

Same pattern as Everyone Active/Southwark: look up the venue's activity ID(s) —
Decathlon centres typically expose one ID per pricing tier — from the network
tab on `activities.decathlon.co.uk`, and add them to `activityIds` in
`DecathlonPickleballRequestStrategy`.
