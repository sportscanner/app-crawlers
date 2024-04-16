# ---PIP PACKAGES---#
import json
import time as pytime
from datetime import date, datetime, time, timedelta

import pandas as pd
import requests
from typing import List
import streamlit as st
import streamlit_shadcn_ui as ui
from streamlit_searchbox import st_searchbox

from shuttlebot.backend.database import load_sports_centre_mappings, engine
from shuttlebot.backend.geolocation.api import (
    get_postcode_metadata,
    postcode_autocompletion,
    validate_uk_postcode,
)
from shuttlebot.backend.geolocation.schemas import PostcodesResponseModel
from shuttlebot.backend.utils import find_consecutive_slots, format_consecutive_slots_groupings
import shuttlebot.backend.database as db
from shuttlebot.frontend.config import DEFAULT_MAPPINGS_SELECTION
from shuttlebot.frontend.utils import (
    load_css_styles, generate_carousal_with_data
)

# -- Page specific settings: title/description/icons etc --
page_title = "Shuttle Bot"
layout: str = "centered"
st.set_page_config(
    page_title=page_title,
    page_icon="🔖",
    layout=layout,
    initial_sidebar_state="collapsed",
)


cards_css = load_css_styles("./shuttlebot/frontend/cards.css")
dropdown_css = load_css_styles("./shuttlebot/frontend/dropdown.css")
brandings_css = load_css_styles("./shuttlebot/frontend/brandings.css")

st.html(f"<style>{cards_css}</style>")
st.html(f"<style>{dropdown_css}</style>")
st.html(f"<style>{brandings_css}</style>")


st.title(f"🔖{page_title}")
st.subheader("Find badminton slots for upcoming week, `90x` faster")
# st.caption("Currently supports `Better Org.` badminton courts (in London)")

# App layouts and logic starts here

today = date.today()
raw_dates = [today + timedelta(days=i) for i in range(6)]
dates = [date.strftime("%Y-%m-%d") for date in raw_dates]


# GLOBAL: Read the JSON file
@st.cache_data
def cached_mappings():
    sports_centre_lists = db.get_all_rows(
        db.engine, table=db.SportsVenue,
        expression=db.select(db.SportsVenue)
    )
    return [sports_centre.venue_name for sports_centre in sports_centre_lists]


sports_centre_names = cached_mappings()
options = st.multiselect(
    "Pick your preferred playing locations",
    sports_centre_names,
    sports_centre_names[:DEFAULT_MAPPINGS_SELECTION],
    # default select first "n" centres from mappings file
    disabled=False,
)

st.toggle(label="Select all locations", key="all_options_switch", value=False)
if st.session_state["all_options_switch"]:
    options = sports_centre_names


postcode_input = st_searchbox(
    postcode_autocompletion,
    label="Find badminton availability near you",
    placeholder="Enter your postcode (default: Central London)",
    key="postcode_input_autocompletion",
)

start_time_filter, end_time_filter, consecutive_slots_filter = st.columns(3)
with start_time_filter:
    start_time_filter_input = st.time_input("Slots ranging from", time(18, 00))
with end_time_filter:
    end_time_filter_input = st.time_input("Slots ranging upto", time(22, 00))
with consecutive_slots_filter:
    consecutive_slots_input = st.radio(
        "Want consecutive slots?",
        [2, 3, 4],
        horizontal=True,
    )


carousel_container = st.container()
with carousel_container:
    consecutive_slots: List[List[db.SportScanner]] = find_consecutive_slots(5)
    generate_carousal_with_data(
        format_consecutive_slots_groupings(consecutive_slots)
    )

# if st.button("Find me badminton slots"):
#     sports_centre_lists = [
#         _sports_centre
#         for _sports_centre in json_data
#         if _sports_centre["name"] in options
#     ]
#
#     with st.status("Fetching desired slots", expanded=False) as status:
#         tic = pytime.time()
#         if postcode_input is not None and validate_uk_postcode(postcode_input) is True:
#             st.success(f"Postcode validation successful")
#             postcode_metadata: PostcodesResponseModel = get_postcode_metadata(
#                 postcode_input
#             )
#         else:
#             st.warning(
#                 "Incorrect/No postcode specified - searching near **central london**"
#             )
#             postcode_metadata: PostcodesResponseModel = get_postcode_metadata(
#                 postcode="WC2N 5DU"  # TODO: this is a central london placeholder
#             )
#         st.write(f"Fetching slots data for dates {dates[0]} to {dates[-1]}")
#         try:
#             display_df, available_slots_with_preferences = slots_scanner(
#                 sports_centre_lists,
#                 dates,
#                 start_time=start_time_filter_input.strftime("%H:%M"),
#                 end_time=end_time_filter_input.strftime("%H:%M"),
#                 postcode_search=postcode_metadata,
#             )
#             st.write(f"calculating {consecutive_slots_input} consecutive slots")
#             groupings_for_consecutive_slots: list = find_consecutive_slots(
#                 sports_centre_lists,
#                 dates,
#                 available_slots_with_preferences,
#                 consecutive_slots_input,
#             )
#             st.write("Sorting outputs for final results")
#             sorted_consecutive_slot_groupings = sorted(
#                 groupings_for_consecutive_slots,
#                 key=lambda grouping: (
#                     grouping[0]["date"],
#                     grouping[0]["nearest_distance"],
#                     grouping[0]["parsed_start_time"],
#                 ),
#             )
#             status.update(
#                 label=f"Processing complete in {pytime.time() - tic:.2f}s",
#                 state="complete",
#                 expanded=False,
#             )
#         except:
#             status.update(label="Failed to fetch slots", state="error", expanded=True)
#
#     carousel_items, show_all_slots = get_carousal_card_items(
#         sorted_consecutive_slot_groupings, consecutive_slots_input, dates
#     )
#     # Create a container to hold the carousel
#     carousel_container = st.container()
#     # Create the horizontal card carousel
#     with carousel_container:
#         st.markdown(
#             f"""
#             <div class="horizontal-scroll">
#                 {" ".join(f'<div class="card" style="background-color: {bg_color};">{text}</div>' for bg_color, text in carousel_items)}
#             </div>
#             """,
#             unsafe_allow_html=True,  # Render the HTML content
#         )
#
#     st.divider()
#     with st.expander("Display all available slots", expanded=show_all_slots):
#         st.dataframe(display_df, use_container_width=True, hide_index=True)
