from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
from typing import Optional, List
from sqlmodel import Session, select
from sportscanner.storage.postgres.tables import PlayerProfile


def _haversine_miles(lat1, lon1, lat2, lon2) -> float:
    R = 3958.8
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


class PlayerProfileRepository:
    def __init__(self, engine):
        self.engine = engine

    def upsert(self, kinde_user_id: str, display_name: str, postcode_district: str,
               latitude: Optional[float], longitude: Optional[float],
               sports: list, skill_level: dict, availability: dict,
               is_discoverable: bool = True) -> PlayerProfile:
        with Session(self.engine) as session:
            profile = session.get(PlayerProfile, kinde_user_id)
            if profile:
                profile.display_name = display_name
                profile.postcode_district = postcode_district
                profile.latitude = latitude
                profile.longitude = longitude
                profile.is_discoverable = is_discoverable
                profile.sports = sports
                profile.skill_level = skill_level
                profile.availability = availability
                profile.updated_at = datetime.utcnow()
            else:
                profile = PlayerProfile(
                    kinde_user_id=kinde_user_id,
                    display_name=display_name,
                    postcode_district=postcode_district,
                    latitude=latitude,
                    longitude=longitude,
                    is_discoverable=is_discoverable,
                    sports=sports,
                    skill_level=skill_level,
                    availability=availability,
                )
                session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile

    def get(self, kinde_user_id: str) -> Optional[PlayerProfile]:
        with Session(self.engine) as session:
            return session.get(PlayerProfile, kinde_user_id)

    def delete(self, kinde_user_id: str) -> bool:
        with Session(self.engine) as session:
            profile = session.get(PlayerProfile, kinde_user_id)
            if not profile:
                return False
            session.delete(profile)
            session.commit()
            return True

    def find_near(self, lat: float, lon: float, radius_miles: float,
                  exclude_user_id: str, sport: Optional[str] = None) -> List[dict]:
        """Return discoverable players within radius_miles, ordered by distance."""
        with Session(self.engine) as session:
            stmt = select(PlayerProfile).where(
                PlayerProfile.is_discoverable == True,
                PlayerProfile.latitude.isnot(None),
                PlayerProfile.longitude.isnot(None),
                PlayerProfile.kinde_user_id != exclude_user_id,
            )
            profiles = session.exec(stmt).all()

        results = []
        for p in profiles:
            dist = _haversine_miles(lat, lon, p.latitude, p.longitude)
            if dist <= radius_miles:
                if sport and sport.lower() not in [s.lower() for s in (p.sports or [])]:
                    continue
                results.append({
                    "kinde_user_id": p.kinde_user_id,
                    "display_name": p.display_name,
                    "postcode_district": p.postcode_district,
                    "sports": p.sports or [],
                    "skill_level": p.skill_level or {},
                    "availability": p.availability or {},
                    "distance_miles": round(dist, 1),
                })
        results.sort(key=lambda x: x["distance_miles"])
        return results
