from typing import Optional

from fastapi import HTTPException
from sportscanner.storage.postgres.user_repository import PostgresUserRepository
from sportscanner.storage.postgres.database import engine


class UserService:
    def __init__(self):
        self.repo = PostgresUserRepository(engine)

    def get_full_profile(self, kinde_user_id: str) -> dict:
        profile = self.repo.get_full_profile(kinde_user_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"No user found: {kinde_user_id}")
        return profile

    def register(self, kinde_user_id: str, full_name: str, email: str) -> None:
        """Called on first login — creates user + empty preferences rows."""
        self.repo.upsert_user(kinde_user_id, full_name, email)
        # Ensure a preferences row exists so onboarding=False is queryable
        self.repo.upsert_preferences(kinde_user_id, {}, onboarding_completed=False)

    def update(self, kinde_user_id: str, full_name: str, email: str, preferences: dict, onboarding: Optional[bool]) -> None:
        self.repo.upsert_user(kinde_user_id, full_name, email)
        self.repo.upsert_preferences(kinde_user_id, preferences, onboarding_completed=onboarding)
