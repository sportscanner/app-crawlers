# SportScanner auth.md

## Public search

Agents can search courts without registration, a token or a SportScanner account using `POST https://api.sportscanner.co.uk/search/{sport}?date=YYYY-MM-DD`. Venue lookup and social session search are also public. Read [the API guide](https://api.sportscanner.co.uk/agents.md).

## MCP with user consent

The Streamable HTTP MCP endpoint is `https://api.sportscanner.co.uk/mcp`.

1. Fetch [protected resource metadata](https://api.sportscanner.co.uk/.well-known/oauth-protected-resource/mcp).
2. Fetch the advertised authorization server's [OAuth metadata](https://api.sportscanner.co.uk/.well-known/oauth-authorization-server). Use its endpoints and supported methods as the source of truth.
3. Use the advertised dynamic client registration endpoint when supported by your MCP client. Registration identifies a client; it does not grant access or create a user account.
4. Run the authorization-code flow with PKCE S256 and the user's interactive consent. Redirect URIs must be permitted by the server. Never collect the user's password.
5. Send the granted access token as `Authorization: Bearer <token>`. Refresh/revoke using the advertised endpoints.

The MCP proxy fronts the existing Kinde login. There are currently no custom MCP scopes. Existing personal API tokens (`ssc_...`) created by a signed-in user in SportScanner's developer console are also accepted. Treat them as secrets; users can revoke them in the console.

SportScanner does not implement autonomous agent account provisioning, verified-email claims, ID-JAG exchange, client-credentials grants or Auth.md-specific registration methods. There is no `agent_auth` registration contract. Use public REST for anonymous queries or the existing user-consented MCP flow. User profile, token management and notifications remain protected and are outside the public search integration.
