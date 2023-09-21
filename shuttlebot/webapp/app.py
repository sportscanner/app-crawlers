# ---PIP PACKAGES---#
import datetime
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from shuttlebot.scanner.script import get_mappings, slots_scanner
from shuttlebot.webapp.utils import hide_streamlit_brandings, icon

# -- Page specific settings: title/description/icons etc --
page_title = "Shuttle Bot"
layout = "wide"
st.set_page_config(
    page_title=page_title,
    page_icon="🏸",
    layout=layout,
    initial_sidebar_state="collapsed",
)

st.title(f"🏸{page_title}")

st.markdown(
    """
    ##### Find badminton slots for upcoming week, 50x faster
    Currently supports `Better Org.` badminton courts (in London)
    """
)
hide_streamlit_brandings()

## ---------------------------------

today = date.today()
raw_dates = [today + timedelta(days=i) for i in range(6)]
dates = [date.strftime("%Y-%m-%d") for date in raw_dates]


# GLOBAL: Read the JSON file
@st.cache_data
def cached_mappings():
    json_data = get_mappings()
    return json_data


json_data = cached_mappings()
options = st.multiselect(
    "Pick your preferred playing locations",
    [x["name"] for x in json_data],
    [x["name"] for x in json_data][:4],
)

start_time_filter, end_time_filter = st.columns(2)
with start_time_filter:
    start_time_filter_input = st.time_input("Slots ranging from", datetime.time(17, 30))
with end_time_filter:
    end_time_filter_input = st.time_input("Slots ranging upto", datetime.time(22, 00))

if st.button("Find me badminton slots"):
    # Convert the JSON data to a list of dictionaries
    # st.info(options)
    sports_centre_lists = [
        _sports_centre
        for _sports_centre in json_data
        if _sports_centre["name"] in options
    ]

    with st.spinner("No need to grab a coffee, we should be done quickly"):
        slots_dataframe = slots_scanner(
            sports_centre_lists,
            dates,
            start_time=start_time_filter_input.strftime("%H:%M"),
            end_time=end_time_filter_input.strftime("%H:%M"),
        )
    st.table(slots_dataframe)
