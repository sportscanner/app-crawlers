"""Public market insights: occupancy, estimated booking value, pricing, supply
and planning pipeline per sport. Read-only and anonymous, like search."""

from fastapi import APIRouter, HTTPException, Path, Query, Response
from starlette import status

from sportscanner.api.routers.core.schemas import SportscannerSupportedSports
from sportscanner.insights import service
from sportscanner.insights.planning import PLANNING_TOPICS, planning_summary
from sportscanner.insights.boroughs import borough_name
from sportscanner.insights import planner
from sportscanner.api.routers.insights.schemas import HistoricalReport

router = APIRouter()

# Reports are rebuilt at most every 10 minutes server-side; let browsers and the
# CDN reuse them for 5.
_CACHE_HEADER = "public, max-age=300, stale-while-revalidate=600"


@router.get("/")
def insights_overview(response: Response):
    """Headline numbers for every sport."""
    response.headers["Cache-Control"] = _CACHE_HEADER
    return service.overview()


@router.get("/planning")
def planning_applications(
    response: Response,
    topic: str = Query("padel", description=f"One of {', '.join(PLANNING_TOPICS)}"),
):
    """London planning applications mentioning the sport, via PlanIt."""
    if topic not in PLANNING_TOPICS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported planning topic: {topic!r}. Must be one of {list(PLANNING_TOPICS)}",
        )
    summary = planning_summary(topic)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Planning data is temporarily unavailable")
    response.headers["Cache-Control"] = _CACHE_HEADER
    return summary


@router.get("/{sport}")
def market_report(response: Response, sport: SportscannerSupportedSports = Path(...), borough: str = Query(None, max_length=64)):
    """London market report for one sport."""
    response.headers["Cache-Control"] = _CACHE_HEADER
    if borough and not borough_name(borough):
        raise HTTPException(status_code=404, detail="Unknown London borough")
    return service.market_report(sport.value, borough)


@router.get("/{sport}/history", response_model=HistoricalReport)
def historical_report(
    response: Response,
    sport: SportscannerSupportedSports = Path(...),
    days: int = Query(90, ge=7, le=400),
    borough: str = Query(None, max_length=64),
    venue: str = Query(None, min_length=1, max_length=16),
):
    """Daily observed prices, matched price index and observed supply."""
    if borough and not borough_name(borough):
        raise HTTPException(status_code=404, detail="Unknown London borough")
    if venue and not service.venue_report(sport.value, venue):
        raise HTTPException(status_code=404, detail="Venue not found for this sport")
    response.headers["Cache-Control"] = _CACHE_HEADER
    return service.historical_report(sport.value, days, borough, venue)


@router.get("/{sport}/catchment")
def catchment_report(
    response: Response,
    sport: SportscannerSupportedSports = Path(...),
    latitude: float = Query(..., ge=49, le=61),
    longitude: float = Query(..., ge=-8, le=2),
    radius: float = Query(3, ge=0.5, le=20),
):
    response.headers["Cache-Control"] = _CACHE_HEADER
    return planner.catchment(sport.value, latitude, longitude, radius)


@router.get("/{sport}/constraints")
def site_constraints(
    sport: SportscannerSupportedSports = Path(...),
    latitude: float = Query(..., ge=49, le=61),
    longitude: float = Query(..., ge=-8, le=2),
):
    try:
        return planner.constraints(latitude, longitude)
    except Exception:
        raise HTTPException(status_code=503, detail="Planning Data is temporarily unavailable")


@router.get("/{sport}/venues/{composite_key}")
def venue_report(
    response: Response,
    sport: SportscannerSupportedSports = Path(...),
    composite_key: str = Path(..., min_length=1, max_length=16),
):
    """Benchmarks, demand profile and local competition for one venue."""
    report = service.venue_report(sport.value, composite_key)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found for this sport")
    response.headers["Cache-Control"] = _CACHE_HEADER
    return report
