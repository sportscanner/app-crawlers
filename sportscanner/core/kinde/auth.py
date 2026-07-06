from sportscanner.variables import settings
import httpx
from fastapi import HTTPException

# Shared, connection-pooled async client (module-level, never closed - lives
# for the process lifetime). Every call site here used to open a brand new
# httpx.Client() (fresh TCP+TLS handshake) per request via a *synchronous*
# call inside an async route handler - on a single-worker server that blocks
# the entire event loop for the duration of both Kinde round-trips, so any
# other concurrent request queues behind it. Reusing one AsyncClient keeps
# connections alive (skips repeat handshakes) and lets requests interleave.
_client = httpx.AsyncClient()


async def get_kinde_access_token(refresh_token: str):
    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "error_description": "Refresh token not provided.",
            },
        )
    if refresh_token.lower().startswith("bearer "):
        refresh_token = refresh_token.split(" ", 1)[1].strip()

    url = f"{settings.KINDE_DOMAIN}/oauth2/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": settings.KINDE_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = await _client.post(url, data=payload, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())
    return response.json().get("access_token")


async def get_kinde_user_details(access_token: str):
    url = f"{settings.KINDE_DOMAIN}/oauth2/user_profile"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = await _client.get(url, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())
    return response.json()
