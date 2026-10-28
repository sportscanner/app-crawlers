"""Provider registry for the crawl queue.

The scheduler and worker share one registry keyed by a stable provider slug.
Venues are matched to a provider by `organisation_website`, which is already
stored on every `sportsvenue` row.

This module deliberately imports the crawler classes directly. It is only
imported by `sportscanner.scheduler.*` CLI processes and tests, never by the
API request path.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Mapping, Optional
from urllib.parse import urlparse

from sportscanner.crawlers.parsers.core.fetch_failures import (
    FetchFailure,
    FetchFailureTracker,
    track_fetch_failures,
)
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.storage.postgres.tables import (
    BadmintonMasterTable,
    PadelMasterTable,
    PickleballMasterTable,
    SportsVenue,
    SquashMasterTable,
    TennisMasterTable,
)

from sportscanner.crawlers.parsers.activelambeth.badminton.scraper import (
    ActiveLambethCrawler as ActiveLambethBadmintonCrawler,
)
from sportscanner.crawlers.parsers.activelambeth.squash.scraper import (
    ActiveLambethCrawler as ActiveLambethSquashCrawler,
)
from sportscanner.crawlers.parsers.better.badminton.scraper import (
    BetterLeisureCrawler as BetterBadmintonCrawler,
)
from sportscanner.crawlers.parsers.better.pickleball.scraper import (
    BetterLeisureCrawler as BetterPickleballCrawler,
)
from sportscanner.crawlers.parsers.better.squash.scraper import (
    BetterLeisureCrawler as BetterSquashCrawler,
)
from sportscanner.crawlers.parsers.better.tennis.scraper import (
    BetterLeisureTennisCrawler,
)
from sportscanner.crawlers.parsers.citysports.badminton.scraper import (
    CitySportsCrawler,
)
from sportscanner.crawlers.parsers.clubspark.padel.scraper import (
    ClubSparkPadelCrawler,
)
from sportscanner.crawlers.parsers.clubspark.tennis.scraper import (
    ClubSparkTennisCrawler,
)
from sportscanner.crawlers.parsers.courtreserve.pickleball.scraper import (
    CourtReservePickleballCrawler,
)
from sportscanner.crawlers.parsers.decathlon.pickleball.scraper import (
    DecathlonCrawler,
)
from sportscanner.crawlers.parsers.everyoneactive.badminton.scraper import (
    EveryoneActiveCrawler as EveryoneActiveBadmintonCrawler,
)
from sportscanner.crawlers.parsers.everyoneactive.squash.scraper import (
    EveryoneActiveCrawler as EveryoneActiveSquashCrawler,
)
from sportscanner.crawlers.parsers.gladstonego.padel.scraper import (
    GladstoneGoPadelCrawler,
)
from sportscanner.crawlers.parsers.haringey.badminton.scraper import (
    HaringeyLeisureCrawler,
)
from sportscanner.crawlers.parsers.matchi.padel.scraper import MatchiPadelCrawler
from sportscanner.crawlers.parsers.matchi.tennis.scraper import MatchiTennisCrawler
from sportscanner.crawlers.parsers.matchpoint.padel.scraper import (
    MatchpointPadelCrawler,
)
from sportscanner.crawlers.parsers.mytimeactive.badminton.scraper import (
    MytimeActiveBadmintonCrawler,
)
from sportscanner.crawlers.parsers.mytimeactive.squash.scraper import (
    MytimeActiveSquashCrawler,
)
from sportscanner.crawlers.parsers.padelmates.padel.scraper import (
    PadelMatesPadelCrawler,
)
from sportscanner.crawlers.parsers.placesleisure.badminton.scraper import (
    PlacesLeisureBadmintonCrawler,
)
from sportscanner.crawlers.parsers.placesleisure.pickleball.scraper import (
    PlacesLeisurePickleballCrawler,
)
from sportscanner.crawlers.parsers.playtomic.padel.scraper import (
    PlaytomicPadelCrawler,
)
from sportscanner.crawlers.parsers.playtomic.pickleball.scraper import (
    PlaytomicPickleballCrawler,
)
from sportscanner.crawlers.parsers.playtomic.tennis.scraper import (
    PlaytomicTennisCrawler,
)
from sportscanner.crawlers.parsers.southwarkleisure.badminton.scraper import (
    SouthwarkLeisureCrawler as SouthwarkBadmintonCrawler,
)
from sportscanner.crawlers.parsers.southwarkleisure.pickleball.scraper import (
    SouthwarkLeisureCrawler as SouthwarkPickleballCrawler,
)
from sportscanner.crawlers.parsers.stratfordpadel.padel.scraper import (
    StratfordPadelCrawler,
)
from sportscanner.crawlers.parsers.towerhamlets.badminton.scraper import (
    TowerHamletsCrawler,
)
from sportscanner.crawlers.parsers.uelsportsdock.badminton.scraper import (
    UELSportsDockCrawler,
)
from sportscanner.crawlers.parsers.visionrcl.badminton.scraper import (
    VisionRclBadmintonCrawler,
)
from sportscanner.crawlers.parsers.visionrcl.squash.scraper import (
    VisionRclSquashCrawler,
)

SPORT_TABLES = {
    "badminton": BadmintonMasterTable,
    "squash": SquashMasterTable,
    "pickleball": PickleballMasterTable,
    "padel": PadelMasterTable,
    "tennis": TennisMasterTable,
}


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    organisation_website: str
    crawlers: Mapping[str, Callable[[], BaseCrawler]]
    max_concurrent: int = 2
    min_interval_seconds: float = 0.25
    notes: str = ""

    @property
    def sports(self) -> tuple[str, ...]:
        return tuple(self.crawlers)


KNOWN_PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        "better",
        "https://www.better.org.uk",
        {
            "badminton": BetterBadmintonCrawler,
            "squash": BetterSquashCrawler,
            "pickleball": BetterPickleballCrawler,
            "tennis": BetterLeisureTennisCrawler,
        },
        max_concurrent=4,
    ),
    ProviderSpec(
        "activelambeth",
        "https://active.lambeth.gov.uk/",
        {
            "badminton": ActiveLambethBadmintonCrawler,
            "squash": ActiveLambethSquashCrawler,
        },
    ),
    ProviderSpec(
        "towerhamlets",
        "https://be-well.org.uk/",
        {"badminton": TowerHamletsCrawler},
        max_concurrent=1,
    ),
    ProviderSpec(
        "citysports",
        "https://citysport.org.uk",
        {"badminton": CitySportsCrawler},
        max_concurrent=1,
    ),
    ProviderSpec(
        "uel",
        "https://www.uel.ac.uk",
        {"badminton": UELSportsDockCrawler},
        max_concurrent=1,
        min_interval_seconds=1.0,
    ),
    ProviderSpec(
        "everyoneactive",
        "https://www.everyoneactive.com/",
        {
            "badminton": EveryoneActiveBadmintonCrawler,
            "squash": EveryoneActiveSquashCrawler,
        },
        max_concurrent=1,
        min_interval_seconds=1.0,
    ),
    ProviderSpec(
        "southwark",
        "https://southwarkleisure.co.uk/",
        {
            "badminton": SouthwarkBadmintonCrawler,
            "pickleball": SouthwarkPickleballCrawler,
        },
    ),
    ProviderSpec(
        "decathlon",
        "https://decathlon.co.uk/",
        {"pickleball": DecathlonCrawler},
        max_concurrent=1,
    ),
    ProviderSpec(
        "haringey",
        "https://haringey.gov.uk/",
        {"badminton": HaringeyLeisureCrawler},
    ),
    ProviderSpec(
        "matchi",
        "https://www.matchi.se",
        {"padel": MatchiPadelCrawler, "tennis": MatchiTennisCrawler},
        max_concurrent=2,
        min_interval_seconds=0.5,
    ),
    ProviderSpec(
        "playtomic",
        "https://playtomic.com",
        {
            "padel": PlaytomicPadelCrawler,
            "pickleball": PlaytomicPickleballCrawler,
            "tennis": PlaytomicTennisCrawler,
        },
        max_concurrent=2,
        min_interval_seconds=0.5,
    ),
    ProviderSpec(
        "placesleisure",
        "https://www.placesleisure.org",
        {
            "badminton": PlacesLeisureBadmintonCrawler,
            "pickleball": PlacesLeisurePickleballCrawler,
        },
        max_concurrent=1,
        min_interval_seconds=1.0,
    ),
    ProviderSpec(
        "clubspark",
        "https://clubspark.lta.org.uk",
        {"tennis": ClubSparkTennisCrawler, "padel": ClubSparkPadelCrawler},
        max_concurrent=2,
        min_interval_seconds=0.5,
    ),
    ProviderSpec(
        "courtreserve",
        "https://lemonpickleball.com",
        {"pickleball": CourtReservePickleballCrawler},
        max_concurrent=1,
    ),
    ProviderSpec(
        "mytimeactive",
        "https://www.mytimeactive.co.uk",
        {
            "badminton": MytimeActiveBadmintonCrawler,
            "squash": MytimeActiveSquashCrawler,
        },
        max_concurrent=1,
        min_interval_seconds=1.0,
    ),
    ProviderSpec(
        "visionrcl",
        "https://www.visionrcl.org.uk",
        {"badminton": VisionRclBadmintonCrawler, "squash": VisionRclSquashCrawler},
    ),
    ProviderSpec(
        "padelmates",
        "https://padelmates.se",
        {"padel": PadelMatesPadelCrawler},
    ),
    ProviderSpec(
        "stratfordpadel",
        "https://stratfordpadelclub.matchpoint.com.es",
        {"padel": StratfordPadelCrawler},
        max_concurrent=1,
    ),
    ProviderSpec(
        "matchpoint",
        "https://tpcmatchpoint.com",
        {"padel": MatchpointPadelCrawler},
        max_concurrent=1,
    ),
    ProviderSpec(
        "gladstonego",
        "https://www.gladstonego.cloud",
        {"padel": GladstoneGoPadelCrawler},
        max_concurrent=1,
        min_interval_seconds=1.0,
    ),
)


def normalise_website(value: str) -> str:
    parsed = urlparse(value.strip())
    host = (parsed.netloc or parsed.path).lower()
    path = parsed.path.rstrip("/") if parsed.netloc else ""
    return f"{host}{path}"


PROVIDERS: dict[str, ProviderSpec] = {spec.key: spec for spec in KNOWN_PROVIDERS}
PROVIDER_BY_WEBSITE: dict[str, ProviderSpec] = {
    normalise_website(spec.organisation_website): spec for spec in KNOWN_PROVIDERS
}


def provider_for_website(website: str) -> Optional[ProviderSpec]:
    return PROVIDER_BY_WEBSITE.get(normalise_website(website))


def get_provider(key: str) -> ProviderSpec:
    try:
        return PROVIDERS[key]
    except KeyError as exc:
        raise KeyError(
            f"Unknown provider {key!r}. Known providers: {', '.join(sorted(PROVIDERS))}"
        ) from exc


@dataclass
class FetchOutcome:
    slots: list[UnifiedParserSchema] = field(default_factory=list)
    failures: list[FetchFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def retry_after_seconds(self) -> Optional[float]:
        values = [
            failure.retry_after_seconds
            for failure in self.failures
            if failure.retry_after_seconds is not None
        ]
        return max(values) if values else None

    @property
    def retryable(self) -> bool:
        return any(failure.retryable for failure in self.failures)

    @property
    def error_message(self) -> Optional[str]:
        if not self.failures:
            return None
        return "; ".join(failure.message for failure in self.failures)[:2000]


def fetch_venue_date(
    provider: str,
    sport: str,
    venue: SportsVenue,
    slot_date: date,
) -> FetchOutcome:
    """Run the existing provider fetch for one venue and date.

    The crawler's own concurrency/pacing/fallback logic is reused unchanged.
    The opt-in failure tracker turns the swallowed errors into a strict outcome
    the worker can act on.
    """
    spec = get_provider(provider)
    try:
        factory = spec.crawlers[sport]
    except KeyError as exc:
        raise KeyError(
            f"Provider {provider!r} does not support sport {sport!r}"
        ) from exc

    tracker = FetchFailureTracker()
    try:
        crawler = factory()
        with track_fetch_failures(tracker):
            slots = asyncio.run(crawler.ScraperCoroutines([venue], [slot_date]))
    except Exception as exc:
        return FetchOutcome(
            slots=[],
            failures=[
                FetchFailure(
                    message=f"{provider} {sport} fetch raised: {type(exc).__name__}: {exc!r}",
                    retryable=True,
                )
            ],
        )
    return FetchOutcome(slots=list(slots or []), failures=list(tracker.failures))
