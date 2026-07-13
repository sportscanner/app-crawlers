from datetime import datetime

from fastapi import HTTPException
from sqlmodel import Session, select

from sportscanner.core.stripe import client as stripe_client
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

from ..schemas import GameCreate, GameListOut, GameOut, JoinGameOut, ParticipantOut


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
    user = session.get(User, kinde_user_id)
    return (user.full_name or user.email) if user else "Unknown"


def _to_game_out(session: Session, game: Game) -> GameOut:
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

    def get_game(self, game_id) -> GameOut:
        with Session(engine) as session:
            game = session.get(Game, game_id)
            if game is None:
                raise HTTPException(status_code=404, detail="Game not found.")
            return _to_game_out(session, game)

    def join_game(self, game_id, user_id: str) -> JoinGameOut:
        with Session(engine) as session:
            game = session.get(Game, game_id)
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

            if _paid_count(session, game.id) >= game.capacity:
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
            session.commit()

            return JoinGameOut(
                client_secret=intent.client_secret,
                payment_intent_id=intent.id,
                amount_pence=game.price_pence,
                platform_fee_pence=platform_fee_pence,
            )

    def cancel_game(self, game_id, organizer_id: str) -> None:
        with Session(engine) as session:
            game = session.get(Game, game_id)
            if game is None:
                raise HTTPException(status_code=404, detail="Game not found.")
            if game.organizer_id != organizer_id:
                raise HTTPException(status_code=403, detail="Only the organizer can cancel this game.")
            if game.status in (GameStatus.CANCELLED, GameStatus.COMPLETED):
                raise HTTPException(status_code=400, detail=f"Game is already {game.status}.")

            paid_participants = session.exec(
                select(GameParticipant).where(
                    GameParticipant.game_id == game.id,
                    GameParticipant.status == GameParticipantStatus.PAID,
                )
            ).all()
            for participant in paid_participants:
                stripe_client.refund_payment_intent(participant.stripe_payment_intent_id)
                participant.status = GameParticipantStatus.REFUNDED
                participant.updated_at = datetime.utcnow()
                session.add(participant)

            game.status = GameStatus.CANCELLED
            game.updated_at = datetime.utcnow()
            session.add(game)
            session.commit()
