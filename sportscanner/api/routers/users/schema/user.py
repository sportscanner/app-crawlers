from typing import Union

from pydantic import BaseModel, EmailStr


class UserInCreate(BaseModel):
    fullName: str
    email: EmailStr
    postcode: str
    password: str


class UserOutput(BaseModel):
    id: str
    fullName: str
    email: EmailStr


class UserInUpdate(BaseModel):
    id: str
    fullName: Union[str, None] = None
    email: Union[EmailStr, None] = None
    password: Union[str, None] = None


class UserInLogin(BaseModel):
    email: EmailStr
    password: str


class UserWithToken(BaseModel):
    id: str
    token: str
