import uuid
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, status
from sqlmodel import Session, select

from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.storage.postgres.database import engine
from sportscanner.storage.postgres.tables import Notification, NotificationAck

from .schemas import NotificationIn, NotificationOut, NotificationUpdate

router = APIRouter()


def _get_user_id(Authorization: str) -> str:
    access_token = get_kinde_access_token(refresh_token=Authorization)
    user_details = get_kinde_user_details(access_token)
    return user_details["id"]


@router.get("/", response_model=list[NotificationOut])
async def list_notifications(
    Authorization: str = Header(
        default=None, title="Bearer token to authenticate user"
    ),
):
    """List all active notifications for the current user, with acknowledged_at set when the user has dismissed it."""
    user_id = _get_user_id(Authorization)
    with Session(engine) as session:
        notifications = session.exec(
            select(Notification).where(Notification.active == True).order_by(Notification.created_at.desc())
        ).all()
        acks = {
            ack.notification_id: ack.acknowledged_at
            for ack in session.exec(
                select(NotificationAck).where(NotificationAck.user_id == user_id)
            ).all()
        }
    return [
        NotificationOut(
            id=str(n.id),
            title=n.title,
            message=n.message,
            active=n.active,
            created_at=n.created_at,
            updated_at=n.updated_at,
            acknowledged_at=acks.get(n.id),
        )
        for n in notifications
    ]


@router.post("/{notification_id}/acknowledge", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_notification(
    notification_id: str,
    Authorization: str = Header(
        default=None, title="Bearer token to authenticate user"
    ),
):
    """Mark a notification as acknowledged (dismissed) for the current user."""
    user_id = _get_user_id(Authorization)
    with Session(engine) as session:
        notification = session.get(Notification, notification_id)
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
        existing = session.exec(
            select(NotificationAck).where(
                NotificationAck.user_id == user_id,
                NotificationAck.notification_id == notification_id,
            )
        ).first()
        if not existing:
            session.add(
                NotificationAck(user_id=user_id, notification_id=notification_id)
            )
            session.commit()


# --- Admin: create/update notifications (you can add role checks later) ---


@router.post("/admin", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
async def create_notification(
    body: NotificationIn,
    Authorization: str = Header(
        default=None, title="Bearer token to authenticate user"
    ),
):
    """Create a new notification (all users will see it until they acknowledge)."""
    _get_user_id(Authorization)  # require auth
    notification = Notification(
        id=str(uuid.uuid4()),
        title=body.title,
        message=body.message,
        active=body.active,
    )
    with Session(engine) as session:
        session.add(notification)
        session.commit()
        session.refresh(notification)
    return NotificationOut(
        id=str(notification.id),
        title=notification.title,
        message=notification.message,
        active=notification.active,
        created_at=notification.created_at,
        updated_at=notification.updated_at,
        acknowledged_at=None,
    )


@router.patch("/admin/{notification_id}", response_model=NotificationOut)
async def update_notification(
    notification_id: str,
    body: NotificationUpdate,
    Authorization: str = Header(
        default=None, title="Bearer token to authenticate user"
    ),
):
    """Update a notification (e.g. edit message or set active=false to hide from everyone)."""
    _get_user_id(Authorization)  # require auth
    with Session(engine) as session:
        notification = session.get(Notification, notification_id)
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
        if body.title is not None:
            notification.title = body.title
        if body.message is not None:
            notification.message = body.message
        if body.active is not None:
            notification.active = body.active
        notification.updated_at = datetime.utcnow()
        session.add(notification)
        session.commit()
        session.refresh(notification)
    return NotificationOut(
        id=str(notification.id),
        title=notification.title,
        message=notification.message,
        active=notification.active,
        created_at=notification.created_at,
        updated_at=notification.updated_at,
        acknowledged_at=None,
    )
