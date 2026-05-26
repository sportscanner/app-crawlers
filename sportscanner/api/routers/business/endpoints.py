import hashlib
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Header, HTTPException, Query, status
from jwt import InvalidTokenError
from sqlalchemy import func, text
from sqlmodel import Session, select

import sportscanner.storage.postgres.database as db
from sportscanner.api.routers.business.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    AuthResponse,
    AvailabilityUpsertRequest,
    AvailabilityUpsertResponse,
    BusinessSportKind,
    DashboardSummaryResponse,
    OnboardResponse,
    PartnerLoginRequest,
    PartnerOnboardRequest,
    PartnerProfile,
    SlotDeleteResponse,
    VenueCalendarSlotResponse,
    VenueCreateRequest,
    VenueResponse,
)
from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.storage.postgres.tables import (
    BadmintonMasterTable,
    BusinessApiKey,
    BusinessIngestionEvent,
    BusinessPartner,
    BusinessVenueAccess,
    PickleballMasterTable,
    SportsVenue,
    SquashMasterTable,
)
from sportscanner.storage.postgres.utils import generate_composite_key
from sportscanner.variables import settings

router = APIRouter()


SLOT_MODEL_BY_SPORT = {
    BusinessSportKind.badminton: (BadmintonMasterTable, "Badminton"),
    BusinessSportKind.squash: (SquashMasterTable, "Squash"),
    BusinessSportKind.pickleball: (PickleballMasterTable, "Pickleball"),
}


# -----------------------------
# Helpers
# -----------------------------
def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", value).strip().lower()
    return re.sub(r"[\s_-]+", "-", cleaned).strip("-")


def _hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def _verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def _create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=720)
    payload = {
        "sub": subject,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization")

    auth = authorization.strip()
    if auth.lower().startswith("bearer "):
        auth = auth[7:].strip()
    if not auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization")
    return auth


def _kinde_identity(refresh_token: str) -> tuple[str, str, str]:
    access_token = get_kinde_access_token(refresh_token=refresh_token)
    details = get_kinde_user_details(access_token)

    kinde_user_id = details.get("id")
    email = (details.get("preferred_email") or details.get("email") or "").lower().strip()
    full_name = f"{details.get('first_name', '')} {details.get('last_name', '')}".strip()

    if not kinde_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Kinde user")
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kinde account has no email")

    return kinde_user_id, full_name, email


def _default_partner_name(full_name: str, email: str) -> str:
    if full_name:
        return full_name
    local_part = email.split("@")[0].replace(".", " ").replace("_", " ").strip()
    return local_part.title() if local_part else "Sportscanner Business"


def _default_website(email: str) -> str:
    if "@" not in email:
        return "https://sportscanner.co.uk"

    domain = email.split("@", 1)[1].strip().lower()
    if not domain:
        return "https://sportscanner.co.uk"

    return f"https://{domain}"


def _get_or_create_partner_for_kinde(session: Session, refresh_token: str) -> BusinessPartner:
    kinde_user_id, full_name, email = _kinde_identity(refresh_token)

    partner = session.exec(
        select(BusinessPartner).where(BusinessPartner.kinde_user_id == kinde_user_id)
    ).first()

    if not partner:
        partner = session.exec(
            select(BusinessPartner).where(BusinessPartner.email == email)
        ).first()
        if partner and not partner.kinde_user_id:
            partner.kinde_user_id = kinde_user_id
            partner.updated_at = datetime.utcnow()
            session.add(partner)

    if not partner:
        partner = BusinessPartner(
            name=_default_partner_name(full_name, email),
            website=_default_website(email),
            kinde_user_id=kinde_user_id,
            email=email,
            password_hash=_hash_password(secrets.token_urlsafe(32)),
        )
        session.add(partner)
        session.flush()

        raw_key, key_prefix, key_hash = _create_api_key()
        session.add(
            BusinessApiKey(
                partner_id=partner.id,
                label="Primary Integration Key",
                key_prefix=key_prefix,
                key_hash=key_hash,
            )
        )

    session.commit()
    session.refresh(partner)

    if partner.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Partner account not available")

    return partner


def _get_current_partner(session: Session, authorization: Optional[str]) -> BusinessPartner:
    token = _extract_bearer_token(authorization)

    # Backward compatibility for earlier email/password business tokens.
    try:
        payload = _decode_access_token(token)
        partner_id = payload.get("sub")
        if partner_id:
            partner = session.get(BusinessPartner, partner_id)
            if partner and partner.status == "active":
                return partner
    except HTTPException:
        pass

    return _get_or_create_partner_for_kinde(session, token)


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _create_api_key() -> tuple[str, str, str]:
    raw_key = f"ssb_{secrets.token_urlsafe(36)}"
    key_prefix = raw_key[:12]
    key_hash = _hash_api_key(raw_key)
    return raw_key, key_prefix, key_hash


def _get_partner_from_api_key(session: Session, api_key: Optional[str]) -> BusinessPartner:
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key")

    key_hash = _hash_api_key(api_key)
    key_row = session.exec(
        select(BusinessApiKey).where(
            BusinessApiKey.key_hash == key_hash,
            BusinessApiKey.active.is_(True),
        )
    ).first()

    if not key_row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    partner = session.get(BusinessPartner, key_row.partner_id)
    if not partner or partner.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Partner account not available")

    key_row.last_used_at = datetime.utcnow()
    session.add(key_row)
    session.commit()

    return partner


def _generate_slot_uid(composite_key: str, category: str, slot_date, start_time, end_time) -> str:
    payload = f"{composite_key}-{category}-{slot_date}-{start_time}-{end_time}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _merge_sports(existing: list[str], incoming: list[str]) -> list[str]:
    merged = [*existing]
    for sport in incoming:
        if sport not in merged:
            merged.append(sport)
    return merged


def _assert_venue_ownership(session: Session, partner_id: str, composite_key: str) -> None:
    owner = session.exec(
        select(BusinessVenueAccess).where(BusinessVenueAccess.composite_key == composite_key)
    ).first()
    if owner and owner.partner_id != partner_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This venue is already managed by another partner",
        )


def _ensure_partner_venue_access(session: Session, partner_id: str, composite_key: str) -> None:
    access = session.exec(
        select(BusinessVenueAccess).where(
            BusinessVenueAccess.partner_id == partner_id,
            BusinessVenueAccess.composite_key == composite_key,
        )
    ).first()

    if not access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Partner cannot update this venue. Onboard venue first.",
        )


def _partner_profile(partner: BusinessPartner) -> PartnerProfile:
    return PartnerProfile(
        id=partner.id,
        name=partner.name,
        website=partner.website,
        email=partner.email,
        status=partner.status,
    )


def _venue_response(venue: SportsVenue) -> VenueResponse:
    return VenueResponse(
        composite_key=venue.composite_key,
        venue_name=venue.venue_name,
        organisation=venue.organisation,
        organisation_website=venue.organisation_website,
        slug=venue.slug,
        postcode=venue.postcode,
        address=venue.address,
        latitude=venue.latitude,
        longitude=venue.longitude,
        sports=venue.sports,
    )


# -----------------------------
# Auth
# -----------------------------
@router.post("/auth/onboard", response_model=OnboardResponse, status_code=status.HTTP_201_CREATED)
async def onboard_partner(payload: PartnerOnboardRequest):
    with Session(db.engine) as session:
        email = payload.email.lower().strip()
        existing = session.exec(select(BusinessPartner).where(BusinessPartner.email == email)).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A partner account with this email already exists",
            )

        partner = BusinessPartner(
            name=payload.name.strip(),
            website=str(payload.website),
            email=email,
            password_hash=_hash_password(payload.password),
        )
        session.add(partner)
        session.flush()

        raw_key, key_prefix, key_hash = _create_api_key()
        session.add(
            BusinessApiKey(
                partner_id=partner.id,
                label="Primary Integration Key",
                key_prefix=key_prefix,
                key_hash=key_hash,
            )
        )
        session.commit()
        session.refresh(partner)

    return OnboardResponse(
        access_token=_create_access_token(partner.id),
        partner=_partner_profile(partner),
        initial_api_key=raw_key,
    )


@router.post("/auth/login", response_model=AuthResponse)
async def login_partner(payload: PartnerLoginRequest):
    with Session(db.engine) as session:
        partner = session.exec(
            select(BusinessPartner).where(BusinessPartner.email == payload.email.lower().strip())
        ).first()

        if not partner or not _verify_password(payload.password, partner.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    return AuthResponse(
        access_token=_create_access_token(partner.id),
        partner=_partner_profile(partner),
    )


@router.get("/auth/me", response_model=PartnerProfile)
async def me(Authorization: str = Header(default=None)):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)
        return _partner_profile(partner)


# -----------------------------
# Partner summary + API keys
# -----------------------------
@router.get("/partners/me/summary", response_model=DashboardSummaryResponse)
async def partner_summary(Authorization: str = Header(default=None)):
    from_24h = datetime.utcnow() - timedelta(hours=24)

    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)

        venue_count = session.exec(
            select(func.count(BusinessVenueAccess.id)).where(BusinessVenueAccess.partner_id == partner.id)
        ).one()
        api_key_count = session.exec(
            select(func.count(BusinessApiKey.id)).where(
                BusinessApiKey.partner_id == partner.id,
                BusinessApiKey.active.is_(True),
            )
        ).one()
        recent_event_count = session.exec(
            select(func.count(BusinessIngestionEvent.id)).where(
                BusinessIngestionEvent.partner_id == partner.id,
                BusinessIngestionEvent.created_at >= from_24h,
            )
        ).one()
        recent_slot_count = session.exec(
            select(func.coalesce(func.sum(BusinessIngestionEvent.slots_written), 0)).where(
                BusinessIngestionEvent.partner_id == partner.id,
                BusinessIngestionEvent.created_at >= from_24h,
            )
        ).one()

    return DashboardSummaryResponse(
        venues=int(venue_count or 0),
        api_keys=int(api_key_count or 0),
        events_24h=int(recent_event_count or 0),
        slots_24h=int(recent_slot_count or 0),
    )


@router.get("/partners/me/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(Authorization: str = Header(default=None)):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)
        rows = session.exec(
            select(BusinessApiKey)
            .where(BusinessApiKey.partner_id == partner.id)
            .order_by(BusinessApiKey.created_at.desc())
        ).all()

        return [
            ApiKeyResponse(
                id=row.id,
                label=row.label,
                key_prefix=row.key_prefix,
                active=row.active,
                created_at=row.created_at,
                last_used_at=row.last_used_at,
            )
            for row in rows
        ]


@router.post("/partners/me/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(payload: ApiKeyCreateRequest, Authorization: str = Header(default=None)):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)
        raw_key, key_prefix, key_hash = _create_api_key()
        row = BusinessApiKey(
            partner_id=partner.id,
            label=payload.label.strip(),
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

    return ApiKeyCreateResponse(
        id=row.id,
        label=row.label,
        key_prefix=row.key_prefix,
        api_key=raw_key,
    )


@router.delete("/partners/me/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(key_id: str, Authorization: str = Header(default=None)):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)
        row = session.get(BusinessApiKey, key_id)

        if not row or row.partner_id != partner.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

        row.active = False
        session.add(row)
        session.commit()


# -----------------------------
# Venues
# -----------------------------
@router.get("/venues/me", response_model=list[VenueResponse])
async def my_venues(Authorization: str = Header(default=None)):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)
        rows = session.exec(
            select(SportsVenue)
            .join(BusinessVenueAccess, SportsVenue.composite_key == BusinessVenueAccess.composite_key)
            .where(BusinessVenueAccess.partner_id == partner.id)
            .order_by(SportsVenue.venue_name)
        ).all()

        return [_venue_response(row) for row in rows]


@router.post("/venues/me", response_model=VenueResponse, status_code=status.HTTP_201_CREATED)
async def upsert_venue(payload: VenueCreateRequest, Authorization: str = Header(default=None)):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)

        org_website = str(payload.organisation_website or partner.website).strip()
        slug = payload.slug.strip() if payload.slug else _slugify(payload.venue_name)
        composite_key = generate_composite_key([org_website, slug])

        _assert_venue_ownership(session, partner.id, composite_key)

        venue = session.get(SportsVenue, composite_key)
        sport_values = [sport.value for sport in payload.sports]
        organisation = payload.organisation or partner.name

        if venue:
            venue.organisation = organisation
            venue.organisation_website = org_website
            venue.venue_name = payload.venue_name
            venue.slug = slug
            venue.postcode = payload.postcode
            venue.address = payload.address
            venue.latitude = payload.latitude
            venue.longitude = payload.longitude
            venue.sports = _merge_sports(venue.sports, sport_values)
        else:
            venue = SportsVenue(
                composite_key=composite_key,
                organisation=organisation,
                organisation_website=org_website,
                venue_name=payload.venue_name,
                slug=slug,
                postcode=payload.postcode,
                address=payload.address,
                latitude=payload.latitude,
                longitude=payload.longitude,
                sports=sport_values,
            )
        session.add(venue)
        session.flush()

        existing_access = session.exec(
            select(BusinessVenueAccess).where(
                BusinessVenueAccess.partner_id == partner.id,
                BusinessVenueAccess.composite_key == composite_key,
            )
        ).first()
        if not existing_access:
            session.add(BusinessVenueAccess(partner_id=partner.id, composite_key=composite_key))

        if session.connection().dialect.name == "postgresql":
            session.execute(
                text(
                    "UPDATE public.sportsvenue "
                    "SET srid = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) "
                    "WHERE composite_key = :composite_key"
                ),
                {"composite_key": composite_key},
            )

        partner.updated_at = datetime.utcnow()
        session.add(partner)
        session.commit()
        session.refresh(venue)

        return _venue_response(venue)


@router.post("/venues/claim/{composite_key}", response_model=VenueResponse)
async def claim_venue(composite_key: str, Authorization: str = Header(default=None)):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)

        _assert_venue_ownership(session, partner.id, composite_key)
        venue = session.get(SportsVenue, composite_key)

        if not venue:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")

        existing_access = session.exec(
            select(BusinessVenueAccess).where(
                BusinessVenueAccess.partner_id == partner.id,
                BusinessVenueAccess.composite_key == composite_key,
            )
        ).first()

        if not existing_access:
            session.add(BusinessVenueAccess(partner_id=partner.id, composite_key=composite_key))
            session.commit()

        return _venue_response(venue)


@router.get("/venues/{composite_key}/calendar", response_model=list[VenueCalendarSlotResponse])
async def venue_calendar(
    composite_key: str,
    sport: BusinessSportKind = Query(..., description="Sport to load slots for"),
    date: date = Query(..., description="Date in YYYY-MM-DD format"),
    Authorization: str = Header(default=None),
):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)
        _ensure_partner_venue_access(session, partner.id, composite_key)

        slot_model, default_category = SLOT_MODEL_BY_SPORT[sport]
        rows = session.exec(
            select(slot_model)
            .where(slot_model.composite_key == composite_key)
            .where(slot_model.date == date)
            .order_by(slot_model.category, slot_model.starting_time)
        ).all()

        return [
            VenueCalendarSlotResponse(
                uid=row.uid,
                sport=sport,
                composite_key=row.composite_key,
                date=row.date,
                starting_time=row.starting_time,
                ending_time=row.ending_time,
                category=row.category or default_category,
                price=row.price,
                spaces=row.spaces,
                booking_url=row.booking_url,
                status="available" if row.spaces > 0 else "blocked",
                last_refreshed=row.last_refreshed,
            )
            for row in rows
        ]


@router.delete("/venues/{composite_key}/slots/{sport}/{slot_uid}", response_model=SlotDeleteResponse)
async def delete_slot(
    composite_key: str,
    sport: BusinessSportKind,
    slot_uid: str,
    Authorization: str = Header(default=None),
):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)
        _ensure_partner_venue_access(session, partner.id, composite_key)

        slot_model, _ = SLOT_MODEL_BY_SPORT[sport]
        row = session.get(slot_model, slot_uid)
        if not row or row.composite_key != composite_key:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")

        session.delete(row)
        session.add(
            BusinessIngestionEvent(
                partner_id=partner.id,
                source="portal-delete",
                sport=sport.value,
                composite_key=composite_key,
                slots_received=1,
                slots_written=0,
                request_id=f"delete:{slot_uid}",
            )
        )
        session.commit()

    return SlotDeleteResponse(uid=slot_uid, deleted=True)


# -----------------------------
# Availability ingestion
# -----------------------------
@router.post("/availability/upsert", response_model=AvailabilityUpsertResponse)
async def upsert_from_portal(
    payload: AvailabilityUpsertRequest,
    Authorization: str = Header(default=None),
):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)
        slots_written = _ingest_slots(session, partner, payload)

    return AvailabilityUpsertResponse(
        composite_key=payload.composite_key,
        sport=payload.sport,
        slots_received=len(payload.slots),
        slots_written=slots_written,
    )


@router.post("/integrations/availability/upsert", response_model=AvailabilityUpsertResponse)
async def upsert_from_integration(
    payload: AvailabilityUpsertRequest,
    x_api_key: str = Header(default=None, alias="X-API-Key"),
):
    with Session(db.engine) as session:
        partner = _get_partner_from_api_key(session, x_api_key)
        slots_written = _ingest_slots(session, partner, payload)

    return AvailabilityUpsertResponse(
        composite_key=payload.composite_key,
        sport=payload.sport,
        slots_received=len(payload.slots),
        slots_written=slots_written,
    )


@router.get("/availability/events")
async def availability_events(
    Authorization: str = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    with Session(db.engine) as session:
        partner = _get_current_partner(session, Authorization)
        rows = session.exec(
            select(BusinessIngestionEvent)
            .where(BusinessIngestionEvent.partner_id == partner.id)
            .order_by(BusinessIngestionEvent.created_at.desc())
            .limit(limit)
        ).all()

        return [
            {
                "id": row.id,
                "source": row.source,
                "sport": row.sport,
                "composite_key": row.composite_key,
                "slots_received": row.slots_received,
                "slots_written": row.slots_written,
                "request_id": row.request_id,
                "created_at": row.created_at,
            }
            for row in rows
        ]


def _ingest_slots(session: Session, partner: BusinessPartner, payload: AvailabilityUpsertRequest) -> int:
    _ensure_partner_venue_access(session, partner.id, payload.composite_key)

    if payload.request_id:
        duplicate = session.exec(
            select(BusinessIngestionEvent).where(
                BusinessIngestionEvent.partner_id == partner.id,
                BusinessIngestionEvent.request_id == payload.request_id,
            )
        ).first()
        if duplicate:
            return duplicate.slots_written

    slot_model, default_category = SLOT_MODEL_BY_SPORT[payload.sport]
    unique_rows = {}
    now = datetime.utcnow()

    for slot in payload.slots:
        category = slot.category or default_category
        uid = _generate_slot_uid(
            composite_key=payload.composite_key,
            category=category,
            slot_date=slot.date,
            start_time=slot.starting_time,
            end_time=slot.ending_time,
        )

        unique_rows[uid] = slot_model(
            uid=uid,
            composite_key=payload.composite_key,
            category=category,
            starting_time=slot.starting_time,
            ending_time=slot.ending_time,
            date=slot.date,
            price=slot.price,
            spaces=slot.spaces,
            last_refreshed=now,
            booking_url=str(slot.booking_url) if slot.booking_url else None,
        )

    for uid, row in unique_rows.items():
        existing = session.get(slot_model, uid)
        if existing:
            existing.price = row.price
            existing.spaces = row.spaces
            existing.last_refreshed = row.last_refreshed
            existing.booking_url = row.booking_url
            session.add(existing)
        else:
            session.add(row)

    session.add(
        BusinessIngestionEvent(
            partner_id=partner.id,
            source=payload.source,
            sport=payload.sport.value,
            composite_key=payload.composite_key,
            slots_received=len(payload.slots),
            slots_written=len(unique_rows),
            request_id=payload.request_id,
        )
    )
    session.commit()

    return len(unique_rows)
