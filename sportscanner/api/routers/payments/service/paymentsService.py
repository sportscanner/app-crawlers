from datetime import datetime

from sqlmodel import Session, select

from sportscanner.core.stripe import client as stripe_client
from sportscanner.logger import logging as logger
from sportscanner.storage.postgres.database import engine
from sportscanner.storage.postgres.tables import (
    Game,
    GameParticipant,
    GameParticipantStatus,
    GameStatus,
    StripeConnectedAccount,
)
from sportscanner.variables import settings

from ..schemas import ConnectStatusOut, OnboardingLinkOut


class PaymentsService:

    def create_onboarding_link(self, kinde_user_id: str, email: str) -> OnboardingLinkOut:
        with Session(engine) as session:
            account = session.get(StripeConnectedAccount, kinde_user_id)
            if account is None:
                stripe_account_id = stripe_client.create_express_account(email)
                account = StripeConnectedAccount(
                    kinde_user_id=kinde_user_id,
                    stripe_account_id=stripe_account_id,
                )
                session.add(account)
                session.commit()
                session.refresh(account)

            # Account links expire quickly (a few minutes) — always mint a fresh one
            # rather than trying to cache/reuse across requests.
            refresh_url = f"{settings.FRONTEND_BASE_URL}/settings/payments?refresh=true"
            return_url = f"{settings.FRONTEND_BASE_URL}/settings/payments?onboarding=complete"
            url = stripe_client.create_account_link(account.stripe_account_id, refresh_url, return_url)
            return OnboardingLinkOut(url=url)

    def get_status(self, kinde_user_id: str) -> ConnectStatusOut:
        with Session(engine) as session:
            account = session.get(StripeConnectedAccount, kinde_user_id)
            if account is None:
                return ConnectStatusOut(
                    connected=False, charges_enabled=False, payouts_enabled=False, details_submitted=False
                )

            # Best-effort live refresh in case the account.updated webhook hasn't
            # landed yet (e.g. user just finished onboarding and came straight back).
            try:
                live = stripe_client.retrieve_account_status(account.stripe_account_id)
                account.charges_enabled = live["charges_enabled"]
                account.payouts_enabled = live["payouts_enabled"]
                account.details_submitted = live["details_submitted"]
                account.updated_at = datetime.utcnow()
                session.add(account)
                session.commit()
            except Exception as exc:  # defensive — status endpoint should still return the last-known DB state
                logger.warning(f"Stripe status refresh failed for {kinde_user_id}: {exc}")

            return ConnectStatusOut(
                connected=True,
                charges_enabled=account.charges_enabled,
                payouts_enabled=account.payouts_enabled,
                details_submitted=account.details_submitted,
            )

    def handle_webhook_event(self, event) -> None:
        event_type = event["type"]
        data = event["data"]["object"]

        if event_type == "account.updated":
            self._handle_account_updated(data)
        elif event_type == "payment_intent.succeeded":
            self._handle_payment_intent_succeeded(data)
        elif event_type == "payment_intent.payment_failed":
            self._set_participant_status(data["id"], GameParticipantStatus.FAILED)
        elif event_type == "charge.refunded":
            payment_intent_id = data.get("payment_intent")
            if payment_intent_id:
                self._set_participant_status(payment_intent_id, GameParticipantStatus.REFUNDED)
        else:
            logger.debug(f"Ignoring unhandled Stripe webhook event: {event_type}")

    def _handle_account_updated(self, account_data) -> None:
        with Session(engine) as session:
            account = session.exec(
                select(StripeConnectedAccount).where(
                    StripeConnectedAccount.stripe_account_id == account_data["id"]
                )
            ).first()
            if account is None:
                return
            account.charges_enabled = account_data.get("charges_enabled", account.charges_enabled)
            account.payouts_enabled = account_data.get("payouts_enabled", account.payouts_enabled)
            account.details_submitted = account_data.get("details_submitted", account.details_submitted)
            account.updated_at = datetime.utcnow()
            session.add(account)
            session.commit()

    def _handle_payment_intent_succeeded(self, payment_intent_data) -> None:
        with Session(engine) as session:
            participant = session.exec(
                select(GameParticipant).where(
                    GameParticipant.stripe_payment_intent_id == payment_intent_data["id"]
                )
            ).first()
            if participant is None:
                logger.warning(f"payment_intent.succeeded for unknown participant: {payment_intent_data['id']}")
                return
            participant.status = GameParticipantStatus.PAID
            participant.updated_at = datetime.utcnow()
            session.add(participant)

            game = session.get(Game, participant.game_id)
            if game is not None:
                paid_count = session.exec(
                    select(GameParticipant).where(
                        GameParticipant.game_id == game.id,
                        GameParticipant.status == GameParticipantStatus.PAID,
                    )
                ).all()
                if len(paid_count) >= game.capacity:
                    game.status = GameStatus.FULL
                    game.updated_at = datetime.utcnow()
                    session.add(game)

            session.commit()

    def _set_participant_status(self, payment_intent_id: str, status: GameParticipantStatus) -> None:
        with Session(engine) as session:
            participant = session.exec(
                select(GameParticipant).where(GameParticipant.stripe_payment_intent_id == payment_intent_id)
            ).first()
            if participant is None:
                return
            participant.status = status
            participant.updated_at = datetime.utcnow()
            session.add(participant)
            session.commit()
