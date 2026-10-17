# SportScanner auth.md

## Public REST and MCP search

Court availability, venue information, prices and provider booking links are public. No SportScanner account, registration, API key, bearer token or OAuth flow is required.

- REST: `POST https://api.sportscanner.co.uk/search/{sport}?date=YYYY-MM-DD`. See [the API guide](https://api.sportscanner.co.uk/agents.md).
- MCP: `https://api.sportscanner.co.uk/mcp` over Streamable HTTP, with authentication set to **None** in your client. Initialize the connection, then list and call tools.

Existing connectors configured with SportScanner OAuth should be reconnected without authentication. Personal API tokens are no longer needed or checked for these public queries. Public MCP does not issue or accept account access grants and publishes no OAuth protected-resource or authorization-server metadata.

## Private account data

Website sign-in uses Kinde to retain your profile, preferences and favourites and personalize the website. Profile, preference, notification and legacy credential-management endpoints still require the existing Kinde authentication. They are not exposed as MCP tools. Public tools cannot read or change a user's account.

## Booking boundary

SportScanner returns public availability snapshots and provider booking links. It cannot reserve courts, take payment or complete bookings. A provider may require its own account to book. Never collect a user's password or bypass provider login gates.
