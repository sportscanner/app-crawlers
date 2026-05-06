import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select, text

from sportscanner.storage.postgres.database import engine
from sportscanner.storage.postgres.tables import Match, MatchPlayer, MatchScore, MatchStatus, User
from sportscanner.core.splitwise.client import create_expense
from sportscanner.variables import settings
from sportscanner.logger import logging as logger

from ..schemas import MatchCreate, MatchOut, MatchSplit, PlayerOut, ScoreOut, LeaderboardEntry


def _determine_winner(scores: list[MatchScore]) -> Optional[int]:
    """Return winning team (1 or 2) based on game count, or None if tied."""
    team1_wins = sum(1 for s in scores if s.team1_score > s.team2_score)
    team2_wins = sum(1 for s in scores if s.team2_score > s.team1_score)
    if team1_wins > team2_wins:
        return 1
    if team2_wins > team1_wins:
        return 2
    return None


def _build_match_out(match: Match, session: Session) -> MatchOut:
    players = session.exec(
        select(MatchPlayer).where(MatchPlayer.match_id == match.id)
    ).all()
    scores = session.exec(
        select(MatchScore).where(MatchScore.match_id == match.id).order_by(MatchScore.game_number)
    ).all()
    return MatchOut(
        id=match.id,
        venue_name=match.venue_name,
        sport=match.sport,
        match_type=match.match_type,
        played_at=match.played_at,
        duration_minutes=match.duration_minutes,
        winning_team=match.winning_team,
        total_cost=match.total_cost,
        status=match.status,
        splitwise_expense_id=match.splitwise_expense_id,
        splitwise_error=match.splitwise_error,
        players=[
            PlayerOut(
                id=p.id,
                email=p.email,
                display_name=p.display_name,
                team=p.team,
                is_creator=p.is_creator,
                splitwise_notified=p.splitwise_notified,
            )
            for p in players
        ],
        scores=[
            ScoreOut(id=s.id, game_number=s.game_number, team1_score=s.team1_score, team2_score=s.team2_score)
            for s in scores
        ],
        created_at=match.created_at,
    )


class MatchService:

    def create_match(self, created_by: str, creator_email: str, body: MatchCreate) -> MatchOut:
        with Session(engine) as session:
            # Build score objects first to determine winner
            score_objs = [
                MatchScore(game_number=s.game_number, team1_score=s.team1_score, team2_score=s.team2_score)
                for s in body.scores
            ]
            winning_team = _determine_winner(score_objs)

            match = Match(
                created_by=created_by,
                venue_name=body.venue_name,
                sport=body.sport,
                match_type=body.match_type,
                played_at=body.played_at,
                duration_minutes=body.duration_minutes,
                winning_team=winning_team,
                total_cost=body.total_cost,
            )
            session.add(match)
            session.flush()  # get match.id

            # Resolve emails server-side — never trust emails from the client
            creator_email_lower = creator_email.lower()
            for p in body.players:
                user = session.get(User, p.kinde_user_id)
                resolved_email = user.email if user else ""
                session.add(MatchPlayer(
                    match_id=match.id,
                    email=resolved_email,
                    display_name=p.display_name,
                    team=p.team,
                    is_creator=resolved_email.lower() == creator_email_lower,
                ))

            for s in body.scores:
                session.add(MatchScore(
                    match_id=match.id,
                    game_number=s.game_number,
                    team1_score=s.team1_score,
                    team2_score=s.team2_score,
                ))

            session.commit()
            session.refresh(match)
            return _build_match_out(match, session)

    def list_matches(self, kinde_user_id: str) -> list[MatchOut]:
        with Session(engine) as session:
            created = session.exec(
                select(Match).where(Match.created_by == kinde_user_id)
            ).all()
            created_ids = {m.id for m in created}

            user = session.get(User, kinde_user_id)
            participating: list[Match] = []
            if user:
                player_rows = session.exec(
                    select(MatchPlayer).where(MatchPlayer.email == user.email)
                ).all()
                extra_ids = {p.match_id for p in player_rows} - created_ids
                if extra_ids:
                    participating = session.exec(
                        select(Match).where(Match.id.in_(extra_ids))
                    ).all()

            all_matches = list(created) + participating
            all_matches.sort(key=lambda m: m.played_at, reverse=True)
            return [_build_match_out(m, session) for m in all_matches]

    def get_match(self, match_id: uuid.UUID) -> Optional[MatchOut]:
        with Session(engine) as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            return _build_match_out(match, session)

    async def split_match(
        self, match_id: uuid.UUID, created_by: str, total_cost: Decimal
    ) -> Optional[MatchOut]:
        with Session(engine) as session:
            match = session.get(Match, match_id)
            if not match or match.created_by != created_by:
                return None
            if match.status == MatchStatus.SPLIT:
                return _build_match_out(match, session)

            creator = session.get(User, created_by)
            players = session.exec(
                select(MatchPlayer).where(MatchPlayer.match_id == match_id)
            ).all()

            match.total_cost = total_cost
            match.status = MatchStatus.SPLIT
            match.updated_at = datetime.utcnow()
            session.add(match)
            session.commit()
            session.refresh(match)

            if settings.SPLITWISE_API_KEY and creator:
                time_str = match.played_at.strftime("%H:%M")
                date_str = match.played_at.strftime("%Y-%m-%d")
                description = f"{match.venue_name} ({date_str} {time_str})"
                participant_emails = [p.email for p in players if not p.is_creator]
                expense_id, splitwise_error, failed_emails = await create_expense(
                    description=description,
                    total_cost=total_cost,
                    creator_email=creator.email,
                    participant_emails=participant_emails,
                    api_key=settings.SPLITWISE_API_KEY,
                )
                if expense_id:
                    match.splitwise_expense_id = expense_id
                match.splitwise_error = splitwise_error
                session.add(match)

                for p in players:
                    p.splitwise_notified = p.email.lower() not in {e.lower() for e in failed_emails} if expense_id else False
                    session.add(p)

                session.commit()
                session.refresh(match)
            else:
                logger.warning("SPLITWISE_API_KEY not set — skipping Splitwise expense creation.")

            return _build_match_out(match, session)

    def get_leaderboard(self, sport: Optional[str] = None) -> list[LeaderboardEntry]:
        with Session(engine) as session:
            sport_filter = "AND m.sport = :sport" if sport else ""
            stmt = text(f"""
                SELECT
                    mp.email,
                    mp.display_name,
                    COUNT(DISTINCT mp.match_id) AS matches_played,
                    COUNT(DISTINCT CASE WHEN m.winning_team = mp.team THEN mp.match_id END) AS wins
                FROM public.match_player mp
                JOIN public.match m ON m.id = mp.match_id
                WHERE 1=1 {sport_filter}
                GROUP BY mp.email, mp.display_name
                ORDER BY wins DESC, matches_played DESC
                LIMIT 50
            """)
            if sport:
                stmt = stmt.bindparams(sport=sport)
            rows = session.execute(stmt).all()

            entries = []
            for row in rows:
                matches = row.matches_played or 0
                wins = row.wins or 0
                entries.append(LeaderboardEntry(
                    email=row.email,
                    display_name=row.display_name,
                    matches_played=matches,
                    wins=wins,
                    win_rate=round(wins / matches, 3) if matches > 0 else 0.0,
                ))
            return entries
