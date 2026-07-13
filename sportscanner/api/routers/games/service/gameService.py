from datetime import datetime, timedelta

import stripe as stripe_sdk
from fastapi import HTTPException
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
    User,
)
from sportscanner.variables import settings

from ..schemas import (
    CancelGameOut,
    GameCreate,
    GameDetailOut,
    GameListOut,
    GameOut,
    JoinGameOut,
    ParticipantOut,
    ParticipantPublicOut,
)

# How long an unconfirmed join is held before its reserved capacity slot is
# released back to the game. Counting only PAID participants against capacity
# (the original implementation) left a multi-minute window — the time it takes
# a user to complete Stripe checkout — during which two concurrent joiners could
# both pass the capacity check and both eventually pay, oversubscribing the game.
# Counting live PENDING reservations closes that window; this TTL stops an
# abandoned checkout from permanently squatting on a slot.
STALE_PENDING_MINUTES = 15


def _paid_count(session: Session, game_id) -> int:
    return len(
        session.exec(
            select(GameParticipant).where(
                GameParticipant.game_id == game_id,
                GameParticipant.status == GameParticipantStatus.PAID,
            )
        ).all()
    )


def _display_name(session: Session, kinde_user_id: str) -> str:
    """Never falls back to a real email address — this is returned to
    unauthenticated callers (GET /games, GET /games/{id}) and other
    participants, none of whom are entitled to see another user's email."""
    user = session.get(User, kinde_user_id)
    if user and user.full_name:
        return user.full_name
    return "Player"


def _expire_stale_pending_reservations(session: Session, game_id) -> None:
    """Releases capacity held by PENDING participants whose checkout was
    abandoned (older than STALE_PENDING_MINUTES). Cancels the underlying
    PaymentIntent so a late confirmation can't succeed after the slot has
    already been given to someone else — if Stripe reports the intent is no
    longer cancelable, the user actually completed payment in the meantime,
    so we leave it for the payment_intent.succeeded webhook to reconcile."""
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_PENDING_MINUTES)
    stale = session.exec(
        select(GameParticipant).where(
            GameParticipant.game_id == game_id,
            GameParticipant.status == GameParticipantStatus.PENDING,
            GameParticipant.created_at < cutoff,
        )
    ).all()
    for participant in stale:
        try:
            stripe_client.cancel_payment_intent(participant.stripe_payment_intent_id)
            participant.status = GameParticipantStatus.FAILED
            participant.updated_at = datetime.utcnow()
            session.add(participant)
        except stripe_sdk.error.InvalidRequestError as exc:
            logger.info(
                f"Not expiring participant {participant.id}: PaymentIntent "
                f"{participant.stripe_payment_intent_id} no longer cancelable ({exc}) — likely already paid."
            )
    session.commit()


def _active_reservation_count(session: Session, game_id) -> int:
    """PAID + still-live PENDING participants — this is what must be compared
    against capacity. Counting PAID alone (the original implementation) let
    concurrent joiners oversell a game during the checkout window; call
    _expire_stale_pending_reservations first so abandoned checkouts don't
    permanently block real capacity."""
    return len(
        session.exec(
            select(GameParticipant).where(
                GameParticipant.game_id == game_id,
                GameParticipant.status.in_([GameParticipantStatus.PAID, GameParticipantStatus.PENDING]),
            )
        ).all()
    )


def _to_participant_public_out(session: Session, p: GameParticipant) -> ParticipantPublicOut:
    return ParticipantPublicOut(
        id=str(p.id),
        display_name=_display_name(session, p.user_id),
        status=p.status,
        joined_at=p.joined_at,
    )


def _to_game_detail_out(session: Session, game: Game, viewer_id: str | None) -> GameDetailOut:
    """Public shape — GET /games/{id}. No organizer_id, no participant user_id/amount_pence.
    `viewer_id` is the optionally-authenticated caller's Kinde ID (None if anonymous
    or the token failed to resolve) — used only to compute `is_organizer`, never returned."""
    participants = session.exec(
        select(GameParticipant).where(GameParticipant.game_id == game.id).order_by(GameParticipant.joined_at)
    ).all()
    paid = sum(1 for p in participants if p.status == GameParticipantStatus.PAID)
    return GameDetailOut(
        id=str(game.id),
        organizer_name=_display_name(session, game.organizer_id),
        venue_name=game.venue_name,
        sport=game.sport,
        scheduled_at=game.scheduled_at,
        duration_minutes=game.duration_minutes,
        capacity=game.capacity,
        spots_remaining=max(game.capacity - paid, 0),
        price_pence=game.price_pence,
        currency=game.currency,
        platform_fee_percent=game.platform_fee_percent,
        platform_fee_fixed_pence=game.platform_fee_fixed_pence,
        status=game.status,
        notes=game.notes,
        participants=[_to_participant_public_out(session, p) for p in participants],
        created_at=game.created_at,
        is_organizer=viewer_id is not None and viewer_id == game.organizer_id,
    )


def _to_game_out(session: Session, game: Game) -> GameOut:
    """Organizer-only full shape — GET /games/mine, POST /games/."""
    participants = session.exec(
        select(GameParticipant).where(GameParticipant.game_id == game.id).order_by(GameParticipant.joined_at)
    ).all()
    paid = sum(1 for p in participants if p.status == GameParticipantStatus.PAID)
    return GameOut(
        id=str(game.id),
        organizer_id=game.organizer_id,
        organizer_name=_display_name(session, game.organizer_id),
        venue_name=game.venue_name,
        sport=game.sport,
        scheduled_at=game.scheduled_at,
        duration_minutes=game.duration_minutes,
        capacity=game.capacity,
        spots_remaining=max(game.capacity - paid, 0),
        price_pence=game.price_pence,
        currency=game.currency,
        platform_fee_percent=game.platform_fee_percent,
        platform_fee_fixed_pence=game.platform_fee_fixed_pence,
        status=game.status,
        notes=game.notes,
        participants=[
            ParticipantOut(
                id=str(p.id),
                user_id=p.user_id,
                display_name=_display_name(session, p.user_id),
                status=p.status,
                amount_pence=p.amount_pence,
                joined_at=p.joined_at,
            )
            for p in participants
        ],
        created_at=game.created_at,
    )


class GameService:

    def create_game(self, organizer_id: str, body: GameCreate) -> GameOut:
        with Session(engine) as session:
            account = session.get(StripeConnectedAccount, organizer_id)
            if account is None or not account.charges_enabled:
                raise HTTPException(
                    status_code=400,
                    detail="Connect your Stripe account and finish onboarding before creating a paid game.",
                )
            if body.capacity < 1:
                raise HTTPException(status_code=400, detail="Capacity must be at least 1.")
            if body.price_pence < 1:
                raise HTTPException(status_code=400, detail="Price must be greater than zero.")

            game = Game(
                organizer_id=organizer_id,
                venue_name=body.venue_name,
                sport=body.sport,
                scheduled_at=body.scheduled_at,
                duration_minutes=body.duration_minutes,
                capacity=body.capacity,
                price_pence=body.price_pence,
                notes=body.notes,
                platform_fee_percent=settings.PLATFORM_FEE_PERCENT,
                platform_fee_fixed_pence=settings.PLATFORM_FEE_FIXED_PENCE,
            )
            session.add(game)
            session.commit()
            session.refresh(game)
            return _to_game_out(session, game)

    def list_open_games(self, sport: str | None = None) -> list[GameListOut]:
        with Session(engine) as session:
            statement = select(Game).where(
                Game.status == GameStatus.OPEN,
                Game.scheduled_at > datetime.utcnow(),
            )
            if sport:
                statement = statement.where(Game.sport == sport)
            games = session.exec(statement.order_by(Game.scheduled_at)).all()
            return [
                GameListOut(
                    id=str(game.id),
                    organizer_name=_display_name(session, game.organizer_id),
                    venue_name=game.venue_name,
                    sport=game.sport,
                    scheduled_at=game.scheduled_at,
                    capacity=game.capacity,
                    spots_remaining=max(game.capacity - _paid_count(session, game.id), 0),
                    price_pence=game.price_pence,
                    currency=game.currency,
                    status=game.status,
                )
                for game in games
            ]

    def list_my_games(self, organizer_id: str) -> list[GameOut]:
        with Session(engine) as session:
            games = session.exec(
                select(Game).where(Game.organizer_id == organizer_id).order_by(Game.scheduled_at.desc())
            ).all()
            return [_to_game_out(session, game) for game in games]

    def get_game(self, game_id, viewer_id: str | None = None) -> GameDetailOut:
        with Session(engine) as session:
            game = session.get(Game, game_id)
            if game is None:
                raise HTTPException(status_code=404, detail="Game not found.")
            return _to_game_detail_out(session, game, viewer_id)

    def join_game(self, game_id, user_id: str) -> JoinGameOut:
        # Expiry runs in its own short transaction, before the row lock below is
        # taken — it commits internally (each Stripe cancel + status update should
        # land even if the join attempt itself later fails for an unrelated reason),
        # and committing while still holding the FOR UPDATE lock would release it early.
        with Session(engine) as session:
            _expire_stale_pending_reservations(session, game_id)

        with Session(engine) as session:
            # Row-locks the game for the duration of this transaction so two
            # concurrent joins for the same game can't both read a stale
            # capacity count — the second request blocks here until the first
            # commits (or rolls back), then re-reads an up-to-date count.
            game = session.exec(select(Game).where(Game.id == game_id).with_for_update()).first()
            if game is None:
                raise HTTPException(status_code=404, detail="Game not found.")
            if game.organizer_id == user_id:
                raise HTTPException(status_code=400, detail="You can't join a game you're organizing.")
            if game.status != GameStatus.OPEN:
                raise HTTPException(status_code=400, detail=f"Game is not open to join (status: {game.status}).")
            if game.scheduled_at <= datetime.utcnow():
                raise HTTPException(status_code=400, detail="Game has already started.")

            already_paid = session.exec(
                select(GameParticipant).where(
                    GameParticipant.game_id == game.id,
                    GameParticipant.user_id == user_id,
                    GameParticipant.status == GameParticipantStatus.PAID,
                )
            ).first()
            if already_paid is not None:
                raise HTTPException(status_code=400, detail="You've already joined this game.")

            # Reuse a still-live pending reservation instead of minting a second
            # PaymentIntent — also stops a user from repeatedly calling /join to
            # eat up all remaining capacity with their own unpaid reservations.
            existing_pending = session.exec(
                select(GameParticipant).where(
                    GameParticipant.game_id == game.id,
                    GameParticipant.user_id == user_id,
                    GameParticipant.status == GameParticipantStatus.PENDING,
                )
            ).first()
            if existing_pending is not None:
                intent = stripe_client.retrieve_payment_intent(existing_pending.stripe_payment_intent_id)
                return JoinGameOut(
                    client_secret=intent.client_secret,
                    payment_intent_id=intent.id,
                    amount_pence=existing_pending.amount_pence,
                    platform_fee_pence=existing_pending.platform_fee_pence,
                )

            if _active_reservation_count(session, game.id) >= game.capacity:
                raise HTTPException(status_code=400, detail="Game is full.")

            organizer_account = session.get(StripeConnectedAccount, game.organizer_id)
            if organizer_account is None or not organizer_account.charges_enabled:
                raise HTTPException(
                    status_code=400,
                    detail="The organizer's payment account is not currently able to receive payments.",
                )

            platform_fee_pence = stripe_client.compute_platform_fee_pence(
                game.price_pence, game.platform_fee_percent, game.platform_fee_fixed_pence
            )
            intent = stripe_client.create_game_join_payment_intent(
                organizer_stripe_account_id=organizer_account.stripe_account_id,
                price_pence=game.price_pence,
                platform_fee_pence=platform_fee_pence,
                currency=game.currency,
                game_id=str(game.id),
                participant_user_id=user_id,
            )

            participant = GameParticipant(
                game_id=game.id,
                user_id=user_id,
                stripe_payment_intent_id=intent.id,
                amount_pence=game.price_pence,
                platform_fee_pence=platform_fee_pence,
            )
            session.add(participant)
            session.commit()  # releases the row lock taken above

            return JoinGameOut(
                client_secret=intent.client_secret,
                payment_intent_id=intent.id,
                amount_pence=game.price_pence,
                platform_fee_pence=platform_fee_pence,
            )

    def cancel_game(self, game_id, organizer_id: str) -> CancelGameOut:
        # Cancel the game itself first, in its own committed transaction. Refunds
        # are then processed one at a time below — previously a single failed
        # Stripe refund call raised mid-loop, and since everything (including
        # `game.status = CANCELLED`) shared one uncommitted transaction, the
        # exception rolled back the *entire* cancellation: the game was left
        # OPEN/FULL indefinitely even though some participants may have already
        # been refunded on Stripe's side moments earlier in the same loop.
        with Session(engine) as session:
            game = session.get(Game, game_id)
            if game is None:
                raise HTTPException(status_code=404, detail="Game not found.")
            if game.organizer_id != organizer_id:
                raise HTTPException(status_code=403, detail="Only the organizer can cancel this game.")
            if game.status in (GameStatus.CANCELLED, GameStatus.COMPLETED):
                raise HTTPException(status_code=400, detail=f"Game is already {game.status}.")

            game.status = GameStatus.CANCELLED
            game.updated_at = datetime.utcnow()
            session.add(game)
            session.commit()

        refunded_count = 0
        failed_participant_ids: list[str] = []
        with Session(engine) as session:
            paid_participants = session.exec(
                select(GameParticipant).where(
                    GameParticipant.game_id == game_id,
                    GameParticipant.status == GameParticipantStatus.PAID,
                )
            ).all()
            for participant in paid_participants:
                try:
                    stripe_client.refund_payment_intent(participant.stripe_payment_intent_id)
                    participant.status = GameParticipantStatus.REFUNDED
                    participant.updated_at = datetime.utcnow()
                    session.add(participant)
                    session.commit()
                    refunded_count += 1
                except Exception as exc:
                    session.rollback()
                    failed_participant_ids.append(str(participant.id))
                    logger.error(
                        f"Refund failed for participant {participant.id} (game {game_id}): {exc}"
                    )

        return CancelGameOut(refunded_count=refunded_count, failed_participant_ids=failed_participant_ids)
