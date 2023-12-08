# ---PIP PACKAGES---#
import json
import time as pytime
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
import streamlit_shadcn_ui as ui

from shuttlebot.backend.geolocation.api import (
    get_postcode_metadata,
    validate_uk_postcode,
)
from shuttlebot.backend.geolocation.schemas import PostcodesResponseModel
from shuttlebot.backend.script import get_mappings, slots_scanner
from shuttlebot.backend.utils import find_consecutive_slots
from shuttlebot.frontend.config import DEFAULT_MAPPINGS_SELECTION
from shuttlebot.frontend.utils import (
    custom_css_carousal,
    get_carousal_card_items,
    hide_streamlit_brandings,
    icon,
)

# -- Page specific settings: title/description/icons etc --
page_title = "Shuttle Bot"
layout: str = "wide"
st.set_page_config(
    page_title=page_title,
    page_icon="📎",
    layout=layout,
    initial_sidebar_state="collapsed",
)
hide_streamlit_brandings()
custom_css_carousal()

st.title(f"📎{page_title}")
st.subheader("Find badminton slots for upcoming week, `90x` faster")
# st.caption("Currently supports `Better Org.` badminton courts (in London)")

# App layouts and logic starts here

today = date.today()
raw_dates = [today + timedelta(days=i) for i in range(6)]
dates = [date.strftime("%Y-%m-%d") for date in raw_dates]


# GLOBAL: Read the JSON file
@st.cache_data
def cached_mappings():
    json_data = get_mappings()
    return json_data, pd.DataFrame(json_data)


if (
    "all_options_switch" in st.session_state
    and st.session_state["all_options_switch"] is True
):
    st.session_state["disable_court_selection"] = True
    st.session_state["postcode_input_state"] = False
else:
    st.session_state["disable_court_selection"] = False
    st.session_state["all_options_switch"] = False
    st.session_state["postcode_input_state"] = True


json_data, mappings_df = cached_mappings()
options = st.multiselect(
    "Pick your preferred playing locations",
    [x["name"] for x in json_data],
    [x["name"] for x in json_data][
        :DEFAULT_MAPPINGS_SELECTION
    ],  # default select first "n" centres from mappings file
    disabled=st.session_state["disable_court_selection"],
)

ui.switch(default_checked=False, label="Select all locations", key="all_options_switch")
if st.session_state["all_options_switch"]:
    options = [x["name"] for x in json_data]

postcode_input = st.text_input(
    label="Find availability near you",
    placeholder="Enter your postcode to find nearest slots",
    disabled=st.session_state["postcode_input_state"],
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

if st.button("Find me badminton slots"):
    sports_centre_lists = [
        _sports_centre
        for _sports_centre in json_data
        if _sports_centre["name"] in options
    ]

    with st.status("Fetching desired slots", expanded=True) as status:
        tic = pytime.time()
        if len(postcode_input) != 0 and validate_uk_postcode(postcode_input) is True:
            st.success(f"Postcode validation successful")
            postcode_metadata: PostcodesResponseModel = get_postcode_metadata(
                postcode_input
            )
        else:
            st.warning(
                "Incorrect/No postcode specified - searching near **central london**"
            )
            postcode_metadata: PostcodesResponseModel = get_postcode_metadata(
                postcode="WC2N 5DU"  # TODO: this is a central london placeholder
            )
        st.write(f"Fetching slots data for dates {dates[0]} to {dates[-1]}")
        try:
            display_df, available_slots_with_preferences = slots_scanner(
                sports_centre_lists,
                dates,
                start_time=start_time_filter_input.strftime("%H:%M"),
                end_time=end_time_filter_input.strftime("%H:%M"),
                postcode_search=postcode_metadata,
            )
            st.write(f"calculating {consecutive_slots_input} consecutive slots")
            groupings_for_consecutive_slots: list = find_consecutive_slots(
                sports_centre_lists,
                dates,
                available_slots_with_preferences,
                consecutive_slots_input,
            )
            st.write("Sorting outputs for final results")
            sorted_consecutive_slot_groupings = sorted(
                groupings_for_consecutive_slots,
                key=lambda grouping: (
                    grouping[0]["date"],
                    grouping[0]["parsed_start_time"],
                    grouping[0]["nearest_distance"]
                ),
            )
            status.update(
                label=f"Processing complete in {pytime.time() - tic:.2f}s",
                state="complete",
                expanded=False,
            )
        except:
            status.update(label="Failed to fetch slots", state="error", expanded=True)

    carousel_items, show_all_slots = get_carousal_card_items(
        sorted_consecutive_slot_groupings, consecutive_slots_input, dates
    )
    # Create a container to hold the carousel
    carousel_container = st.container()
    # Create the horizontal card carousel
    with carousel_container:
        st.markdown(
            f"""
            <div class="horizontal-scroll">
                {" ".join(f'<div class="card" style="background-color: {bg_color};">{text}</div>' for bg_color, text in carousel_items)}
            </div>
            """,
            unsafe_allow_html=True,  # Render the HTML content
        )

    st.divider()
    with st.expander("Display all available slots", expanded=show_all_slots):
        st.dataframe(display_df, use_container_width=True, hide_index=True)
