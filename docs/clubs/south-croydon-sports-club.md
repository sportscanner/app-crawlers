# South Croydon Sports Club

1 venue, `https://www.southcroydonsportsclub.com/`, configured in
`venues.json` for `["badminton", "tennis"]`.

## Status: not implemented — dead configuration entry

There is no scraper for this provider. `sportscanner/crawlers/parsers/southcroydonsports/`
contains only a stale `__pycache__` directory for a `requestparser.py` that no
longer exists as source — whatever was there was deleted without removing the
compiled bytecode. It is not imported anywhere in `pipeline.py`, and none of the
`*_scraping_pipeline()` functions reference it.

This venue has never been crawled and never will be until a scraper is written
for it (or the entry is removed from `venues.json` as no longer intended).
`tennis` also isn't one of the sports categories this platform searches at all
(`badminton`, `squash`, `pickleball`, `padel` — see the root `CLAUDE.md`), so even
the sports list here doesn't match what the rest of the system expects.

## If picking this up

Treat it as a new provider from scratch, following the pattern in
`docs/crawlers.md` (implement `AbstractRequestStrategy` +
`AbstractResponseParserStrategy`, wire a `coroutines()` entry point into
`pipeline.py`). There's no existing code to build on here despite the folder
existing. If the decision is instead "we're not going to support this venue",
remove the `venues.json` entry and delete the empty parser folder rather than
leaving it as a silent gap.
