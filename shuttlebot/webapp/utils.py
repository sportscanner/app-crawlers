import streamlit as st


def icon(emoji: str):
    """Shows an emoji as a Notion-style page icon."""
    st.write(
        f'<span style="font-size: 78px; line-height: 1">{emoji}</span>',
        unsafe_allow_html=True,
    )


def hide_streamlit_branding():
    # generic streamlit configuration to hide brandings
    hide_st_style = """<style>
                        #MainMenu {visibility : hidden;}
                        footer {visibility : hidden;}
                        header {visibility : hidden;}
                        .stMultiSelect [data-baseweb=select] span{
                            max-width: 250px;
                            font-size: 0.6rem;
                        }
                        div[data-testid="metric-container"] {
                           background-color: rgba(28, 131, 225, 0.1);
                           border: 1px solid rgba(28, 131, 225, 0.1);
                           padding: 5% 5% 5% 10%;
                           border-radius: 5px;
                           color: rgb(30, 103, 119);
                           overflow-wrap: break-word;
                        }
                    </style>
                    """
    hide_sidebar_hamburger = """
                            <style>
                                [data-testid="collapsedControl"] {
                                    display: none
                                }
                            </style>
                            """
    st.markdown(hide_st_style, unsafe_allow_html=True)
    st.markdown(
        hide_sidebar_hamburger,
        unsafe_allow_html=True,
    )


def custom_css_carousal():
    css_style = """
        <style>
        .horizontal-scroll {{
            display: flex;
            overflow-x: auto;
            white-space: nowrap;
            scrollbar-width: none;
            -ms-overflow-style: none;
        }}
        .horizontal-scroll::-webkit-scrollbar {{
            width: 0px;
            height: 0px;
        }}
        .card {{
            border: 1px solid #ccc;
            padding: 10px;
            margin-right: 10px;
            min-width: 200px;
            border-radius: 10px; /* Adjust the radius as needed */
            word-wrap: break-word; /* Enable word wrapping */
        }}
        </style>
        """
    st.markdown(
        css_style,
        unsafe_allow_html=True,  # Render the HTML content
    )


def get_carousal_card_items(
    groupings_for_consecutive_slots: list, consecutive_slots_input: int, dates
):
    carousel_items = []
    if len(groupings_for_consecutive_slots) > 0:
        for group_id in range(len(groupings_for_consecutive_slots)):
            gather_slots_starting_times = []
            for j in groupings_for_consecutive_slots[group_id]:
                gather_slots_starting_times.append(
                    j["parsed_start_time"].strftime("%H:%M")
                )

            carousel_card_elements = {
                "heading": None,
                "venue": None,
                "date": groupings_for_consecutive_slots[group_id][0]["date"].strftime(
                    "%Y-%m-%d (%A)"
                ),
            }
            carousel_items.append(
                (
                    "#FAFAFA",
                    f"<div style='white-space: pre-wrap;'><span style='color:#e74c3c'>"  # Line 1
                    f"{consecutive_slots_input} consecutive slots</span></div>"
                    f"<div style='white-space: pre-wrap;'>"
                    f"{groupings_for_consecutive_slots[group_id][0]['name']}</div>"  # Line 2
                    f"<div style='white-space: pre-wrap;'><strong>"  # Line 3
                    f"{carousel_card_elements['date']}</strong></div><br>"
                    f"<div style='white-space: pre-wrap;'>Slots starting at"  # Line 4
                    f" {', '.join(gather_slots_starting_times)}</div>",
                )
            )
        flag = False
    else:
        carousel_items.append(
            (
                "#F3F2F1",
                f"<div style='white-space: pre-wrap;'>Selected centres do not have "
                f"{consecutive_slots_input} consecutive slots</div>",
            )
        )
        flag = True
    return carousel_items, flag
