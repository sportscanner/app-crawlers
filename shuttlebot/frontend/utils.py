import streamlit as st
from typing import List

from shuttlebot.backend.utils import ConsecutiveSlotsCarousalDisplay

st.cache_data()
def load_css_styles(file_path: str):
    with open(file_path, "r") as f:
        css = f.read()
    return css


def generate_carousal_with_data(
        consecutive_slots_groupings: List[ConsecutiveSlotsCarousalDisplay]
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
