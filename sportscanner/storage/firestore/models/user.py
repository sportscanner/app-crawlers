from datetime import datetime
from typing import Union
from uuid import UUID

from pydantic import BaseModel, EmailStr


class User(BaseModel):
    id: str
    fullName: str
    email: EmailStr
    password: str
    created_at: str


class UserInCreate(BaseModel):
    fullName: str
    email: EmailStr
    password: str


class UserOutput(BaseModel):
    id: str
    fullName: str
    email: EmailStr
