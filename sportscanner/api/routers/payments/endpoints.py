from fastapi import APIRouter, Header, HTTPException, Request, status

from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.core.stripe import client as stripe_client
from sportscanner.logger import logging as logger

from .schemas import ConnectStatusOut, OnboardingLinkOut
from .service.paymentsService import PaymentsService

router = APIRouter()


def _kinde_identity(refresh_token: str) -> tuple[str, str]:
    """Returns (kinde_user_id, email) from a refresh token."""
    access_token = get_kinde_access_token(refresh_token=refresh_token)
    details = get_kinde_user_details(access_token)
    return details["id"], details.get("preferred_email", "")


@router.post("/connect/onboard-link", response_model=OnboardingLinkOut)
async def create_onboarding_link(
    Authorization: str = Header(default=None, title="Bearer token to authenticate user"),
):
    """Returns a Stripe-hosted onboarding URL — creates the Express account on first call."""
    user_id, email = _kinde_identity(Authorization)
    return PaymentsService().create_onboarding_link(user_id, email)


@router.get("/connect/status", response_model=ConnectStatusOut)
async def get_connect_status(
    Authorization: str = Header(default=None, title="Bearer token to authenticate user"),
):
    """Whether the current user has connected + finished Stripe onboarding (can receive game payments)."""
    user_id, _ = _kinde_identity(Authorization)
    return PaymentsService().get_status(user_id)


@router.post("/webhook", status_code=status.HTTP_200_OK, include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default=None, alias="stripe-signature"),
):
    """
    Stripe webhook receiver — no Kinde auth, verified instead via the
    'stripe-signature' header against STRIPE_WEBHOOK_SECRET. Must read the raw
    body (not a parsed JSON model) since signature verification is over the
    exact bytes Stripe sent.
    """
    payload = await request.body()
    event = stripe_client.construct_webhook_event(payload, stripe_signature)
    try:
        PaymentsService().handle_webhook_event(event)
    except Exception as exc:
        # Log and 200 anyway where possible is tempting, but a 500 here makes Stripe
        # retry the event — safer than silently dropping a payment/account update.
        logger.error(f"Error handling Stripe webhook event {event.get('type')}: {exc}")
        raise HTTPException(status_code=500, detail="Webhook handling failed")
    return {"received": True}
