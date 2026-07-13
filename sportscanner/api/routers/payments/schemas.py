from pydantic import BaseModel


class OnboardingLinkOut(BaseModel):
    url: str


class ConnectStatusOut(BaseModel):
    connected: bool  # False if the user has never started onboarding
    charges_enabled: bool  # True once Stripe will let this account receive payments
    payouts_enabled: bool
    details_submitted: bool
