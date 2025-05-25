import itertools
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from loguru import logger as logging
from pydantic import BaseModel
from sqlmodel import select

from sportscanner.storage.postgres.database import (
    engine,
    get_all_rows,
)
from sportscanner.storage.postgres.tables import BadmintonMasterTable, SportsVenue
from sportscanner.utils import timeit


class ConsecutiveSlotsCarousalDisplay(BaseModel):
    """Model to store information displayed via Card carousal"""

    distance: str
    venue: str
    organisation: str
    raw_date: date
    date: str
    group_start_time: time
    group_end_time: time
    slots_starting_times: str
    bookings_url: Optional[str]


@timeit
def find_consecutive_slots(
    consecutive_count: int = 3,
    starting_time: time = time(18, 00),
    ending_time: time = time(22, 00),
    starting_date: date = datetime.now().date(),
    ending_date: date = datetime.now().date() + timedelta(days=3),
) -> List[List[BadmintonMasterTable]]:
    """Finds consecutively overlapping slots i.e. end time of one slot overlaps with start time of
    another and calculates the `n` consecutive slots
    Returns: List of grouped consecutively occurring slots
    """

    slots = get_all_rows(
        engine,
        BadmintonMasterTable,
        select(BadmintonMasterTable)
        .where(BadmintonMasterTable.spaces > 0)
        .where(BadmintonMasterTable.starting_time >= starting_time)
        .where(BadmintonMasterTable.ending_time <= ending_time)
        .where(BadmintonMasterTable.date >= starting_date)
        .where(BadmintonMasterTable.date <= ending_date),
    )
    sports_centre_lists = get_all_rows(engine, SportsVenue, select(SportsVenue))
    dates: List[date] = list(set([row.date for row in slots]))
    consecutive_slots_list = []
    parameter_sets = [(x, y) for x, y in itertools.product(dates, sports_centre_lists)]

    for target_date, venue in parameter_sets:
        venue = venue.slug
        logging.debug(
            f"Extracting consecutive slots for venue slug: {venue} / date: {target_date}"
        )
        while True:
            consecutive_slots = []
            filtered_slots = [
                slot
                for slot in slots
                if slot.venue_slug == venue and slot.date == target_date
            ]
            sorted_slots = sorted(filtered_slots, key=lambda slot: slot.starting_time)
            logging.debug(sorted_slots)

            for i in range(len(sorted_slots) - 1):
                slot1 = sorted_slots[i]
                slot2 = sorted_slots[i + 1]

                if slot1.ending_time >= slot2.starting_time:
                    consecutive_slots.append(slot1)

                    if len(consecutive_slots) == consecutive_count - 1:
                        consecutive_slots.append(slot2)
                        break
                else:
                    consecutive_slots = []

            if len(consecutive_slots) == consecutive_count:
                consecutive_slots_list.append(consecutive_slots)
                # Remove the found slots from the data
                slots.remove(consecutive_slots[0])

            else:
                break  # No more consecutive slots found

    logging.debug(
        f"Top 3 Consecutive slots calculations:\n{consecutive_slots_list[:3]}"
    )
    return consecutive_slots_list


@timeit
def format_consecutive_slots_groupings(
    consecutive_slots: List[List[BadmintonMasterTable]],
) -> List[ConsecutiveSlotsCarousalDisplay]:
    temp = []
    sports_venues: List[SportsVenue] = get_all_rows(
        engine, SportsVenue, select(SportsVenue)
    )
    venue_slug_map = {venue.slug: venue for venue in sports_venues}
    for group_for_consecutive_slots in consecutive_slots:
        gather_slots_starting_times = []
        for slot in group_for_consecutive_slots:
            gather_slots_starting_times.append(slot.starting_time.strftime("%H:%M"))

        display_message_slots_starting_times: str = (
            "Slots starting at " f"{', '.join(gather_slots_starting_times)}"
        )
        initial_slot_in_group: BadmintonMasterTable = group_for_consecutive_slots[0]
        final_slot_in_group: BadmintonMasterTable = group_for_consecutive_slots[0]
        # replacing slug with names
        if initial_slot_in_group.venue_slug in venue_slug_map:
            # Replace venue_slug with the corresponding slug from SportsVenue
            venue_name_lookup = venue_slug_map[
                initial_slot_in_group.venue_slug
            ].venue_name

            temp.append(
                ConsecutiveSlotsCarousalDisplay(
                    distance="Greater London, England",
                    venue=venue_name_lookup,
                    organisation=initial_slot_in_group.organisation,
                    raw_date=initial_slot_in_group.date,
                    date=initial_slot_in_group.date.strftime("%Y-%m-%d (%A)"),
                    group_start_time=initial_slot_in_group.starting_time,
                    group_end_time=final_slot_in_group.starting_time,
                    slots_starting_times=display_message_slots_starting_times,
                    bookings_url=initial_slot_in_group.booking_url,
                )
            )
    sorted_groupings_for_consecutive_slots = sorted(
        temp, key=lambda x: (x.distance, x.raw_date, x.group_start_time)
    )
    logging.debug(
        f"Top formatted consecutive slot grouping for Carousal:\n{sorted_groupings_for_consecutive_slots[:1]}"
    )
    return sorted_groupings_for_consecutive_slots
