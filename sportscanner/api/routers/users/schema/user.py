from typing import Union, List, Optional, Dict

from pydantic import BaseModel, EmailStr


class UserOutput(BaseModel):
    id: str
    fullName: str
    email: EmailStr


class UserInCreate(BaseModel):
    kindeUserId: str
    fullName: Optional[str] = None
    email: EmailStr
    postcode: Optional[str] = None
    preferredVenues: Optional[List[str]] = None
    preferredTimes: Optional[Dict[str, List[str]]] = None  # {day: [time_slots]}
    goals: Optional[List[str]] = None
    customPostcodes: Optional[List[str]] = None
    skillBadminton: Optional[str] = None
    skillSquash: Optional[str] = None
    skillPickleball: Optional[str] = None
    onboarding: bool = False
