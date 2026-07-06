from sportscanner.variables import settings
import httpx
from fastapi import HTTPException


def get_kinde_access_token(refresh_token: str):
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

    with httpx.Client() as client:
        response = client.post(url, data=payload, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        return response.json().get("access_token")

def get_kinde_user_details(access_token: str):
    url = f"{settings.KINDE_DOMAIN}/oauth2/user_profile"
    headers = {"Authorization": f"Bearer {access_token}"}

    with httpx.Client() as client:
        response = client.get(url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        return response.json()
