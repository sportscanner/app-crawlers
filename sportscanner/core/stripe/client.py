"""
Thin wrapper around the Stripe SDK for the Games payments feature.

Architecture: Stripe Connect, Express accounts, destination charges.
This is the pattern most early-stage marketplace startups reach for first —
Stripe hosts onboarding (KYC/bank details) and the platform never touches
funds directly, it just tells Stripe how to split each charge:

  PaymentIntent(amount=total, transfer_data={destination: organizer_account},
                application_fee_amount=platform_fee, on_behalf_of=organizer_account)

Stripe settles `amount - application_fee_amount` to the organizer's connected
account balance (paid out on their own Express payout schedule) and the fee
stays in the platform's Stripe balance. Apple Pay / Google Pay need no extra
integration here — they're just payment methods surfaced by Stripe's
PaymentElement on the frontend against the same PaymentIntent.
"""

from typing import Optional

import stripe as stripe_sdk
from fastapi import HTTPException

from sportscanner.variables import settings


def _client() -> None:
    """Configures the SDK's module-level API key. Raises a clear error if unset
    rather than letting every call fail with an opaque Stripe auth error."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured on this environment (STRIPE_SECRET_KEY unset).",
        )
    stripe_sdk.api_key = settings.STRIPE_SECRET_KEY


def create_express_account(email: str) -> str:
    """Creates a new Stripe Express connected account for an organizer. Returns the account ID."""
    _client()
    account = stripe_sdk.Account.create(
        type="express",
        email=email,
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
    )
    return account.id


def create_account_link(stripe_account_id: str, refresh_url: str, return_url: str) -> str:
    """Returns a one-time hosted onboarding URL for the given connected account.
    `refresh_url` is where Stripe sends the user back if the link expires mid-flow;
    `return_url` is where they land after completing (or exiting) onboarding."""
    _client()
    account_link = stripe_sdk.AccountLink.create(
        account=stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return account_link.url


def retrieve_account_status(stripe_account_id: str) -> dict:
    """Returns the current charges_enabled/payouts_enabled/details_submitted flags for an account."""
    _client()
    account = stripe_sdk.Account.retrieve(stripe_account_id)
    return {
        "charges_enabled": account.charges_enabled,
        "payouts_enabled": account.payouts_enabled,
        "details_submitted": account.details_submitted,
    }


def compute_platform_fee_pence(price_pence: int, fee_percent: float, fee_fixed_pence: int) -> int:
    """Platform fee = percent cut + fixed pence, rounded to the nearest penny.
    Intentionally not a token amount — mirrors how Eventbrite/Meetup-style
    organizer fees are structured (see PLATFORM_FEE_PERCENT/FIXED_PENCE in Settings)."""
    return round(price_pence * (fee_percent / 100)) + fee_fixed_pence


def create_game_join_payment_intent(
    organizer_stripe_account_id: str,
    price_pence: int,
    platform_fee_pence: int,
    currency: str,
    game_id: str,
    participant_user_id: str,
) -> stripe_sdk.PaymentIntent:
    """
    Creates a destination-charge PaymentIntent for a user joining a game.
    Card, Apple Pay, and Google Pay are all handled by `automatic_payment_methods`
    — the frontend's Stripe PaymentElement surfaces whichever are available for
    the customer's device/browser against this same PaymentIntent, no separate
    wallet integration needed.
    """
    _client()
    if platform_fee_pence >= price_pence:
        raise HTTPException(status_code=500, detail="Platform fee cannot exceed the game price.")
    return stripe_sdk.PaymentIntent.create(
        amount=price_pence,
        currency=currency,
        automatic_payment_methods={"enabled": True},
        application_fee_amount=platform_fee_pence,
        transfer_data={"destination": organizer_stripe_account_id},
        on_behalf_of=organizer_stripe_account_id,
        metadata={"game_id": game_id, "participant_user_id": participant_user_id},
    )


def refund_payment_intent(payment_intent_id: str) -> None:
    """Refunds a joined participant's payment in full, including the platform fee portion
    (refund_application_fee=True), e.g. when an organizer cancels a game."""
    _client()
    stripe_sdk.Refund.create(
        payment_intent=payment_intent_id,
        refund_application_fee=True,
    )


def construct_webhook_event(payload: bytes, sig_header: Optional[str]) -> stripe_sdk.Event:
    """Verifies and parses an incoming Stripe webhook request body."""
    _client()
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Stripe webhook secret is not configured.")
    try:
        return stripe_sdk.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (stripe_sdk.error.SignatureVerificationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Stripe webhook signature: {exc}")
