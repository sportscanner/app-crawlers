from typing import List

import streamlit as st

from shuttlebot.backend.utils import ConsecutiveSlotsCarousalDisplay


@st.cache_resource
def load_css_styles(file_path: str):
    with open(file_path, "r") as f:
        css = f.read()
    st.html(f"<style>{css}</style>")


@st.cache_resource
def load_page_headers():
    st.markdown(
        """
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20,400,0,0" />
        <div style="display: flex; align-items: center;">
            <span class="material-symbols-outlined" style="font-size: 50px; color: rgb(59, 130, 246);">
                query_stats
            </span>
            <h1 style="color: rgb(59, 130, 246); margin: 0 0 0 10px;">Sportscanner</h1>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data
def load_postcodes_lookup():
    pass  # TODO: use the lookup file `postcodes.csv` to enrich the cards and dataframe


def generate_carousal_with_data(
    consecutive_slots_groupings: List[ConsecutiveSlotsCarousalDisplay],
):
    if len(consecutive_slots_groupings) > 0:
        card_html_template = f"""
        <div class="horizontal-scroll">
        {" ".join(
            f'''
            <div class="card" style="background-color: #f9f9fd;">
                <div style='white-space: pre-wrap;'><span style='color:#6d7e86'>{group.distance}</span></div>
                <div style='white-space: pre-wrap;'>{group.venue}</div>
                <div style='white-space: pre-wrap;'><strong>{group.date}</strong></div><br>
                <div style='white-space: pre-wrap;'>{group.slots_starting_times}</div>
                  <div class="actions">
                    <a class="read" href='{group.bookings_url}' target='_blank'>
                      Visit Bookings Site
                    </a>
                  </div>
            </div>
            '''
            for group in consecutive_slots_groupings
            )
        }
        </div>
        """
        st.html(
            f"""
              {card_html_template}
            """
        )
