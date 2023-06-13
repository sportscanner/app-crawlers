#---PIP PACKAGES---#
import streamlit as st
import pandas as pd
from datetime import date, timedelta
from script import main, metadata, api_requests_to_fetch_slots, filter_and_transform_results, reset_results_cache
import time
import json
import itertools
import datetime
from stqdm import stqdm

# Page specific settings: title/description/icons etc 
page_title = "`Better Org.` Badminton slots finder"
layout = "wide"
st.set_page_config(page_title=page_title, layout=layout, initial_sidebar_state="collapsed")
st.title(f"{page_title}")

st.markdown("""
    ###### This webapp helps parse through all Better Org. badminton courts in London to find ideal slots for the upcoming `6` days
    Author: `Yasir`
    """
    )

# generic streamlit configuration to hide brandings
hide_st_style = """<style>
                    #MainMenu {visibility : hidden;}
                    footer {visibility : hidden;}
                    header {visibility : hidden;}
                    .stMultiSelect [data-baseweb=select] span{
                        max-width: 250px;
                        font-size: 0.6rem;
                    }
                </style>
                """
hide_sidebar_hamburger =  """
                        <style>
                            [data-testid="collapsedControl"] {
                                display: none
                            }
                        </style>
                        """
st.markdown(hide_st_style, unsafe_allow_html=True)
st.markdown(hide_sidebar_hamburger,unsafe_allow_html=True,)

today = date.today()
raw_dates = [today + timedelta(days=i) for i in range(6)]
dates = [date.strftime("%Y-%m-%d") for date in raw_dates]

# GLOBAL: Read the JSON file
with open('./mappings.json', 'r') as file:
    json_data = json.load(file)

options = st.multiselect(
    'Pick your preferred playing locations',
    [x["name"] for x in list(json_data.values())],
    [x["name"] for x in list(json_data.values())][:4])

start_time_filter, end_time_filter = st.columns(2)
with start_time_filter:
    start_time_filter_input = st.time_input('Slots ranging from', datetime.time(17, 30))
with end_time_filter:
    end_time_filter_input = st.time_input('Slots ranging upto', datetime.time(22, 00))

if st.button("Find me badminton slots"):
    # Convert the JSON data to a list of dictionaries
    # st.info(options)
    sports_centre_lists = [_sports_centre for _sports_centre in list(json_data.values()) if _sports_centre["name"] in options] 
    parameter_sets = [(x, y) for x, y in itertools.product(sports_centre_lists, dates)]
    # st.json(sports_centre_lists)
    # st.info(f"{dates} - Starting time: {start_time_filter_input} - Ending time: {end_time_filter_input}")
    
    for (sports_centre, date) in stqdm(parameter_sets, desc="This is a slow task, grab a coffee"):
        api_requests_to_fetch_slots(sports_centre, date)

    slots_dataframe = filter_and_transform_results(
        start_time = start_time_filter_input.strftime('%H:%M'), 
        end_time = end_time_filter_input.strftime('%H:%M')
    )
    reset_results_cache()
    st.table(slots_dataframe)

