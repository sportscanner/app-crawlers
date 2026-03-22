from datetime import datetime
from typing import Union, Dict
from uuid import UUID
from typing import List, Optional

from pydantic import BaseModel, EmailStr


class User(BaseModel):
    kindeUserId: str
    created_at: datetime
    fullName: Optional[str] = None
    email: EmailStr
    postcode: Optional[str] = None
    preferredVenues: Optional[List[str]] = None
    preferredTimes: Optional[Dict[str, List[str]]] = None
    skillBadminton: Optional[str] = None
    skillSquash: Optional[str] = None
    skillPickleball: Optional[str] = None
    onboarding: bool = False


class UserInCreate(BaseModel):
    kindeUserId: str
    fullName: Optional[str] = None
    email: EmailStr
    postcode: Optional[str] = None
    preferredVenues: Optional[List[str]] = None
    preferredTimes: Optional[Dict[str, List[str]]] = None
    skillBadminton: Optional[str] = None
    skillSquash: Optional[str] = None
    skillPickleball: Optional[str] = None
    onboarding: bool = False


class UserInCreateConfirmation(BaseModel):
    kindeUserId: str
    email: EmailStr
    created_at: datetime
