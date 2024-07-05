# ---PIP PACKAGES---#
import json
import time as pytime
from datetime import date, datetime, time, timedelta
from typing import List

import pandas as pd
import requests
import streamlit as st
import streamlit_shadcn_ui as ui
from streamlit_searchbox import st_searchbox

import shuttlebot.backend.database as db
from shuttlebot.backend.database import engine, load_sports_centre_mappings
from shuttlebot.backend.geolocation.api import (
    get_postcode_metadata,
    postcode_autocompletion,
    validate_uk_postcode,
)
from shuttlebot.backend.geolocation.schemas import PostcodesResponseModel
from shuttlebot.backend.pipeline import pipeline_data_refresh
from shuttlebot.backend.utils import (
    find_consecutive_slots,
    format_consecutive_slots_groupings,
)
from shuttlebot.frontend.config import DEFAULT_MAPPINGS_SELECTION
from shuttlebot.frontend.utils import generate_carousal_with_data, load_css_styles

# -- Page specific settings: title/description/icons etc --
page_title = "SportScanner"
layout: str = "wide"
st.set_page_config(
    page_title=page_title,
    layout=layout,
    initial_sidebar_state="collapsed",
)

cards_css = load_css_styles("./shuttlebot/frontend/cards.css")
dropdown_css = load_css_styles("./shuttlebot/frontend/dropdown.css")
brandings_css = load_css_styles("./shuttlebot/frontend/brandings.css")

st.html(f"<style>{cards_css}</style>")
st.html(f"<style>{dropdown_css}</style>")
st.html(f"<style>{brandings_css}</style>")


st.markdown(
    f'<h1 style="color:rgb(59, 130, 246);">{page_title}</h1>', unsafe_allow_html=True
)
st.markdown(
    '<h5 style="color:rgb(15, 60, 130);">Find Your Next Badminton Booking - Quicker and '
    'Centralised</h5>', unsafe_allow_html=True
)
# st.markdown("Find Your Next Badminton Booking - Quicker and Centralised")

# App layouts and logic starts here

today = date.today()
raw_dates = [today + timedelta(days=i) for i in range(6)]
dates = [date.strftime("%Y-%m-%d") for date in raw_dates]


# GLOBAL: Read the JSON file
@st.cache_resource
def cached_mappings():
    sports_centre_lists = db.get_all_rows(
        db.engine, table=db.SportsVenue, expression=db.select(db.SportsVenue)
    )
    return [
        sports_centre.venue_name for sports_centre in sports_centre_lists
    ], sports_centre_lists


sports_centre_names, sports_venues = cached_mappings()

with st.form("my_form"):
    # options = st.multiselect(
    #     "Pick your preferred playing locations",
    #     sports_centre_names,
    #     sports_centre_names[:DEFAULT_MAPPINGS_SELECTION],
    #     # default select first "n" centres from mappings file
    #     disabled=True,
    # )

    st.toggle(
        label="Select all locations",
        key="all_options_switch",
        value=True,
        disabled=True,
    )
    if st.session_state["all_options_switch"]:
        options = sports_centre_names

    date_range_input = st.date_input(
        "Select the dates you want to play at?",
        value=(datetime.now().date(), datetime.now().date() + timedelta(days=6)),
        min_value=datetime.now().date(),
        max_value=datetime.now().date() + timedelta(days=30),
        format="DD/MM/YYYY",
    )
    start_time_filter, end_time_filter, consecutive_slots_filter = st.columns(3)
    with start_time_filter:
        start_time_filter_input = st.time_input("Slots starting from", time(18, 00))
    with end_time_filter:
        end_time_filter_input = st.time_input("Slots available until", time(22, 00))
    with consecutive_slots_filter:
        consecutive_slots_input = st.radio(
            "Want consecutive slots?",
            [2, 3, 4],
            horizontal=True,
        )
    user_preferences_selection = st.form_submit_button("Find me badminton slots")

if user_preferences_selection:
    with st.status("Fetching available badminton slots", expanded=True) as status:
        tic = pytime.time()
        db.pipeline_refresh_decision_based_on_interval(engine, timedelta(minutes=45))
        st.write(f"Fetching slots data for dates **{dates[0]}** to **{dates[-1]}**")
        if (
            db.get_refresh_status_for_pipeline(engine)
            != db.PipelineRefreshStatus.COMPLETED.value
        ):
            st.write(f"Cache miss, data refresh in-progress")
            pipeline_data_refresh()
        else:
            st.write(f"Data is already up-to to date, fetching cache")
        st.write(f"Calculating {consecutive_slots_input} consecutive slots")
        starting_date_input = date_range_input[0]
        ending_date_input = (
            date_range_input[1] if len(date_range_input) > 1 else date_range_input[0]
        )
        consecutive_slots: List[List[db.SportScanner]] = find_consecutive_slots(
            consecutive_slots_input,
            start_time_filter_input,
            end_time_filter_input,
            starting_date_input,
            ending_date_input,
        )

        slots = db.get_all_rows(
            engine,
            db.SportScanner,
            db.select(db.SportScanner)
            .where(db.SportScanner.spaces > 0)
            .where(db.SportScanner.starting_time >= start_time_filter_input)
            .where(db.SportScanner.ending_time <= end_time_filter_input)
            .where(db.SportScanner.date >= starting_date_input)
            .where(db.SportScanner.date <= ending_date_input)
            .order_by(db.SportScanner.date)
            .order_by(db.SportScanner.starting_time),
        )
        slots_dict_list = [model.model_dump() for model in slots]

        # Convert the dictionary list to a pandas DataFrame
        badminton_slots_df = pd.DataFrame(slots_dict_list)
        sports_venues_df = pd.DataFrame([model.model_dump() for model in sports_venues])
        dataframe_for_display = pd.merge(
            badminton_slots_df,
            sports_venues_df[["venue_name", "slug"]],
            left_on="venue_slug",
            right_on="slug",
            how="left",
        )
        dataframe_for_display = dataframe_for_display.loc[
            :,
            [
                "venue_name",
                "date",
                "starting_time",
                "ending_time",
                "price",
                "booking_url",
            ],
        ]

        status.update(
            label=f"Processing complete in {pytime.time() - tic:.2f}s",
            state="complete",
            expanded=False,
        )
    with st.container() as carousel_container:
        formatted_consecutive_slots_groupings = format_consecutive_slots_groupings(
            consecutive_slots
        )
        if len(formatted_consecutive_slots_groupings) == 0:
            st.warning("No consecutive slots found in the selected time/venues")
        else:
            generate_carousal_with_data(formatted_consecutive_slots_groupings)

    st.divider()
    with st.expander("Display all available slots", expanded=True):
        st.dataframe(
            dataframe_for_display,
            column_config={
                "venue_name": "Venue name",
                "date": "Date",
                "starting_time": "Starting Time",
                "ending_time": "Ending Time",
                "price": "Price",
                "booking_url": st.column_config.LinkColumn(
                    label="Bookings Website", display_text="Visit Booking Site"
                ),
            },
            use_container_width=True,
            hide_index=True,
        )
