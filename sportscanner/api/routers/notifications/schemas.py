from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: str
    title: str
    message: str
    active: bool
    created_at: datetime
    updated_at: datetime
    acknowledged_at: Optional[datetime] = None  # Set when current user has dismissed it


class NotificationIn(BaseModel):
    title: str
    message: str
    active: bool = True


class NotificationUpdate(BaseModel):
    title: Optional[str] = None
    message: Optional[str] = None
    active: Optional[bool] = None
