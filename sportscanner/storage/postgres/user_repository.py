from datetime import datetime
from typing import Optional

from sqlmodel import Session

from sportscanner.storage.postgres.tables import User, UserPreferences


class PostgresUserRepository:
    def __init__(self, engine):
        self.engine = engine

    # ── Identity ─────────────────────────────────────────────────────────────

    def upsert_user(self, kinde_user_id: str, full_name: Optional[str], email: str) -> User:
        """Create user row on first login, or update name/email on subsequent logins."""
        with Session(self.engine) as session:
            user = session.get(User, kinde_user_id)
            if user:
                user.full_name = full_name
                user.email = email
                user.updated_at = datetime.utcnow()
            else:
                user = User(kinde_user_id=kinde_user_id, full_name=full_name, email=email)
                session.add(user)
            session.commit()
            session.refresh(user)
            return user

    def get_user(self, kinde_user_id: str) -> Optional[User]:
        with Session(self.engine) as session:
            return session.get(User, kinde_user_id)

    # ── Preferences ───────────────────────────────────────────────────────────

    def get_preferences(self, kinde_user_id: str) -> Optional[UserPreferences]:
        with Session(self.engine) as session:
            return session.get(UserPreferences, kinde_user_id)

    def upsert_preferences(
        self,
        kinde_user_id: str,
        preferences: dict,
        onboarding_completed: bool = False,
    ) -> UserPreferences:
        """
        Merge new preference keys into the existing JSONB blob.
        Existing keys not in `preferences` are preserved.
        """
        with Session(self.engine) as session:
            prefs = session.get(UserPreferences, kinde_user_id)
            if prefs:
                merged = {**(prefs.preferences or {}), **preferences}
                prefs.preferences = merged
                prefs.onboarding_completed = onboarding_completed
                prefs.updated_at = datetime.utcnow()
            else:
                prefs = UserPreferences(
                    kinde_user_id=kinde_user_id,
                    preferences=preferences,
                    onboarding_completed=onboarding_completed,
                )
                session.add(prefs)
            session.commit()
            session.refresh(prefs)
            return prefs

    # ── Combined profile ──────────────────────────────────────────────────────

    def get_full_profile(self, kinde_user_id: str) -> Optional[dict]:
        """Returns merged user + preferences dict, or None if user not found."""
        with Session(self.engine) as session:
            user = session.get(User, kinde_user_id)
            if not user:
                return None
            prefs = session.get(UserPreferences, kinde_user_id)
            return {
                "kindeUserId": user.kinde_user_id,
                "fullName": user.full_name,
                "email": user.email,
                "onboarding": prefs.onboarding_completed if prefs else False,
                "preferences": prefs.preferences if prefs else {},
            }
