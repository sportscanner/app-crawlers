# Southwark Leisure

2 venues, `https://southwarkleisure.co.uk/`. Badminton (both venues), pickleball
(Canada Water only). Code: `sportscanner/crawlers/parsers/southwarkleisure/`.

## API shape

Base: `https://southwarkcouncil.gs-signature.cloud/AWS/api/activity/availability?toUTC={ts}&activityId={activityId}&fromUTC={ts}&locale=en_GB`

A Gladstone "gs-signature" API distinct from both the `better-admin.org.uk` and
`flow.onl` deployments seen elsewhere. Per-venue hardcoded `activityId` strings
(`CWLC` -> `"CWACT00001"`, `CAS` -> `"CAACT00001"`) keyed by `venue.slug`, same
pattern as Everyone Active / Matchi / Playtomic's hardcoded-ID maps.

Auth is a **static, hardcoded API key** sent as a request header:
`AuthenticationKey: M0bi1eProB00king$`. This is baked into the source
(`southwarkleisure/badminton/scraper.py` and `.../pickleball/scraper.py`) rather
than pulled from env config — it appears to be a shared mobile-app key rather
than an account-specific secret, but if this API ever starts rejecting requests,
check whether this key has been rotated before assuming a code bug.

Dates are passed as UTC timestamp ranges (`get_utc_timestamps`), same helper
pattern as Everyone Active and Decathlon.

## Status (July 2026)

Confirmed live: both badminton venues and the one pickleball venue (Canada Water)
return data. No known issues.
