## Sportscanner - search and compare playing venues
![example workflow](https://github.com/sportscanner/app-crawlers/actions/workflows/crawler-pipeline.yml/badge.svg) ![example workflow](https://github.com/sportscanner/app-crawlers/actions/workflows/Automated-PR-tests.yml/badge.svg) ![example workflow](https://github.com/sportscanner/app-crawlers/actions/workflows/deploy-to-registry.yml/badge.svg)

Finding a racket sports court in London (badminton, squash, pickleball, padel)
without an expensive club membership usually means checking several different
booking websites by hand. Sportscanner aggregates them into one search.

### What's implemented

- Crawlers for Better/GLL, Southwark, Tower Hamlets, CitySports, Decathlon, Matchi,
  Playtomic, and others, covering badminton, squash, pickleball, and padel.
- A FastAPI backend: postcode-radius venue search, per-sport availability search
  with time/date/consecutive-slot filtering, user accounts and favourites, personal
  API tokens, and an MCP server for programmatic access.
- PostgreSQL + PostGIS for storage and geospatial distance queries, with a Valkey
  cache in front of the near-static postcode/venue lookups.
- A per-provider circuit breaker and concurrency cap in the crawler layer, so a
  down provider does not burn its full request budget every run.
- A Next.js frontend (separate repository) deployed on Vercel.

### Architecture

Frontend (Vercel) talks to the FastAPI backend (Render), which reads from
PostgreSQL. A separate scheduled crawler pipeline (GitHub Actions) writes to the
same database. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full diagram, and
[`docs/`](docs/) for database, crawler, and API design notes.

## Authors
- [Yasir Khalid](https://www.linkedin.com/in/yasir-khalid)
