# ---PIP PACKAGES---#
import json
import time as pytime
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from shuttlebot.scanner.script import get_mappings, slots_scanner
from shuttlebot.scanner.utils import find_consecutive_slots
from shuttlebot.webapp.config import DEFAULT_MAPPINGS_SELECTION
from shuttlebot.webapp.utils import (
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
    page_icon="🏸",
    layout=layout,
    initial_sidebar_state="collapsed",
    theme="light",  # Set the theme to light mode
)
hide_streamlit_brandings()
custom_css_carousal()

st.title(f"🏸{page_title}")
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


json_data, mappings_df = cached_mappings()
options = st.multiselect(
    "Pick your preferred playing locations",
    [x["name"] for x in json_data],
    [x["name"] for x in json_data][
    :DEFAULT_MAPPINGS_SELECTION
    ],  # default select first "n" centres from mappings file
)

start_time_filter, end_time_filter, consecutive_slots_filter = st.columns(3)
with start_time_filter:
    start_time_filter_input = st.time_input("Slots ranging from", time(18, 00))
with end_time_filter:
    end_time_filter_input = st.time_input("Slots ranging upto", time(22, 00))
with consecutive_slots_filter:
    consecutive_slots_input = st.number_input(
        "Consecutively occurring slots", min_value=2, max_value=4
    )

if st.button("Find me badminton slots"):
    # Convert the JSON data to a list of dictionaries
    # st.info(options)
    sports_centre_lists = [
        _sports_centre
        for _sports_centre in json_data
        if _sports_centre["name"] in options
    ]

    with st.status("Fetching desired slots", expanded=True) as status:
        tic = pytime.time()
        st.write(f"Fetching slots data for dates {dates[0]} to {dates[-1]}")
        display_df, available_slots_with_preferences = slots_scanner(
            sports_centre_lists,
            dates,
            start_time=start_time_filter_input.strftime("%H:%M"),
            end_time=end_time_filter_input.strftime("%H:%M"),
        )
        st.write("Parsing for consecutive slots")
        groupings_for_consecutive_slots: list = find_consecutive_slots(
            sports_centre_lists,
            dates,
            available_slots_with_preferences,
            consecutive_slots_input,
        )
        status.update(
            label=f"Processing complete in {pytime.time() - tic:.2f}s",
            state="complete",
            expanded=False,
        )

    carousel_items, show_all_slots = get_carousal_card_items(
        groupings_for_consecutive_slots, consecutive_slots_input, dates
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
