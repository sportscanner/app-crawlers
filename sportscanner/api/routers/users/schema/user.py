from typing import Union, List, Optional

from pydantic import BaseModel, EmailStr


class UserOutput(BaseModel):
    id: str
    fullName: str
    email: EmailStr

class UserInCreate(BaseModel):
    kindeUserId: str
    fullName: Optional[str]
    email: EmailStr
    postcode: str
    preferredVenues: Optional[List[str]] = None
    onboarding: bool = False
