# Agent discovery and direct search

SportScanner already exposes public, anonymous REST search and an anonymous
MCP server. The readiness changes make these discoverable from the main website
and align MCP court results with the website's existing search rules.

## Published resources

The API owns the API catalog, AI catalog, agent guide, authentication guide,
skills index and skill artifact. The frontend proxies these public documents.
MCP exposes only public read-only tools and does not publish OAuth metadata. Deploy this backend branch before the frontend branch.

- `/.well-known/api-catalog`: RFC 9727 / RFC 9264 Linkset with OpenAPI, guide and liveness links.
- `/.well-known/ai-catalog.json`: API and MCP discovery, representative queries and public CORS.
- `/agents.md`, `/llms-full.txt`: complete public search contract and booking boundary.
- `/auth.md`: anonymous REST/MCP setup and the separate private account boundary.
- `/.well-known/agent-skills/index.json`: v0.2.0 index with a digest of the exact served skill bytes.
- `/.well-known/agent-skills/find-london-courts/SKILL.md`: court search instructions.
- `/mcp/server-card` and `/.well-known/mcp/server-card.json`: current SEP-2127 Server Card extension format. The linked scanner guidance references an older shape; current cards describe identity and remotes, with tools/capabilities negotiated live.
- `/health/`: service liveness, separate from provider freshness.

The frontend adds homepage Link headers, `/llms.txt`, an explicit
`Accept: text/markdown` landing-page response and read-only WebMCP search/venue
tools. HTML remains the browser default. WebMCP is feature-detected; browser
support is required. REST and HTTP MCP work without WebMCP.

Content Signals permit `search` and `ai-input`, matching the user-facing agent
query use case. The existing training-crawler rules are preserved and no new
`ai-train` preference is asserted. SportScanner does not own the underlying
booking providers' content rights.

## Query behavior

`find_available_courts` now delegates to the same REST handler rather than a
separate database query. This excludes past slots and per-person social games,
and supports the same time, price/distance and indoor/outdoor filters. The
existing REST routes, request/response shapes and OpenAPI operation IDs stay
compatible. The MCP tool name and its original required arguments are retained.

Read [the served guide](sportscanner/api/routers/discovery/agents.md) for units,
examples, stale data handling and booking links. SportScanner cannot book or
pay for a court. User-specific endpoints remain protected by Kinde; MCP never exposes account data.

## DNS and deployment follow-up

DNS-AID is not enabled by these commits. The authoritative nameservers are
`dns1.registrar-servers.com` / `dns2.registrar-servers.com`; there is no connected
registrar/DNS management capability in this environment. DNSSEC also requires
coordination with the authoritative host and registrar DS records. Repository
files alone cannot publish or sign the zone.

After both applications are deployed, publish this catalog pointer at the DNS
provider (also useful independently of experimental DNS-AID):

```dns
_catalog._agents.sportscanner.co.uk. 3600 IN TXT "url=https://www.sportscanner.co.uk/.well-known/ai-catalog.json"
```

For DNS-AID, configure an `_index._agents.sportscanner.co.uk` ServiceMode SVCB
record targeting `www.sportscanner.co.uk`, with HTTPS transport ALPN (`h2`)
and port 443, and a capability locator for
`https://www.sportscanner.co.uk/.well-known/ai-catalog.json`. An MCP entry can
target `api.sportscanner.co.uk` and its `/mcp/server-card` descriptor. Use numeric
private-use `keyNNNNN` SvcParamKeys for experimental parameters, agreed with the
consumer, until IANA assigns keys; do not paste draft mnemonic parameter names
into a DNS provider that does not support them. Verify the current draft and
DNS provider support before publishing. Enable DNSSEC and verify authenticated
answers (`AD=true`) through a validating resolver. Do not advertise A2A or a
semantic search endpoint, since neither exists.

DNS-AID is still an Internet-Draft. Follow
[the current draft](https://datatracker.ietf.org/doc/draft-mozleywilliams-dnsop-dnsaid/)
and [RFC 9460](https://www.rfc-editor.org/rfc/rfc9460) rather than treating
experimental record examples as stable production configuration.

## Intentionally unsupported scanner checks

There is no A2A agent, Personal Agent Protocol service, autonomous Auth.md
provisioning, or commerce/payment service. No fictional manifests, registration
methods, grants, JWKS URLs or payment endpoints are published to satisfy checks.
OAuth discovery is intentionally absent because public court/venue tools require no authentication. A scanner may still count this as missing; publishing a fictional protected resource would misrepresent the service.

## Verification

- Backend: `python -m pytest tests -q` with the normal dev environment. The existing crawler fragment tests require ignored `reports/venue-fragments/*.json` fixtures from the developer checkout.
- Frontend: `npm run test:agents`, `npm run build`, and `npx tsc --noEmit`.
- Run the API and frontend locally. Check homepage HTML and Markdown separately, metadata media types and redirects, the skill digest, and the real `POST /search/{sport}` flow for all five sports.
- The local dev database may contain stale or missing data. A 200/empty result verifies the contract, not current provider coverage. Check `last_refreshed` and `healthcheck`.
- After deployment, rescan [Is It Agent Ready](https://isitagentready.com/) against `https://www.sportscanner.co.uk`. The baseline on 17 October 2026 reported Basic Web Presence (level 1). Local tests are not a new production readiness score.

### Results on 17 October 2026

The backend suite passed 44 tests with the existing local crawler fixtures.
The frontend agent suite passed 6 tests, and the production build passed.
Full frontend TypeScript checking reports 23 errors, identical to a clean
checkout of main; no new errors were introduced. HTTP smoke tests passed for
all discovery resources, skill integrity, Markdown and HTML negotiation,
React Flight responses, OAuth issuer consistency and the MCP 401 challenge.
All five local REST sport searches returned 200. A read-only MCP query returned
4 venues and 32 slots from the dev database, with stale freshness flags intact.
The MCP card also validates against the current official extension JSON Schema.

The production browser bundle registered both WebMCP tools against a browser-local
test double and returned 4 venues / 32 slots through the real local API. This
verifies application wiring, not native experimental-browser interoperability.
The existing homepage sport picker and badminton search navigation rendered
without page errors. The T3 collaborative browser later timed out; the final
browser checks used local headless Chromium through Playwright.

## Anonymous MCP migration

MCP now accepts requests without credentials and no longer depends on Kinde discovery or OAuth session storage at startup. Existing OAuth connectors should reconnect with authentication set to None. The developer guide is public at `/developer`; token creation and connected-client UI have been retired because public tools do not use those credentials. Legacy account credential-management routes remain Kinde-protected. Old OAuth grants cannot access private account data or authenticate MCP. No database migration or DNS change is required.

Migration validation: 52 backend tests pass, including anonymous initialize, tools/list, tools/call and rejection of anonymous account reads/writes. A standard MCP SDK client completed a real anonymous court query against the local API, and all five REST sport searches returned 200. Frontend agent tests (6) and the production build pass; full TypeScript checking retains exactly the same 23 existing main-branch errors. The public guide renders without login and makes no credential-management requests.
