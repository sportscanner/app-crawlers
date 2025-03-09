from datetime import datetime
from typing import Union
from uuid import UUID
from typing import List, Optional

from pydantic import BaseModel, EmailStr


class User(BaseModel):
    kindeUserId: str
    created_at: datetime
    fullName: Optional[str]
    email: EmailStr
    postcode: str
    preferredVenues: Optional[List[str]] = None
    onboarding: bool = False


class UserInCreate(BaseModel):
    kindeUserId: str
    fullName: Optional[str]
    email: EmailStr
    postcode: str
    preferredVenues: Optional[List[str]] = None
    onboarding: bool = False


class UserInCreateConfirmation(BaseModel):
    kindeUserId: str
    email: EmailStr
    created_at: datetime
