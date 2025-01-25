from pydantic import EmailStr, BaseModel
from typing import Union
from uuid import UUID
from datetime import datetime


class User(BaseModel):
    id: str
    fullName: str
    email : EmailStr
    password : str
    created_at: str


class UserInCreate(BaseModel):
    fullName: str
    email : EmailStr
    password : str

class UserOutput(BaseModel):
    id : str
    fullName: str
    email : EmailStr