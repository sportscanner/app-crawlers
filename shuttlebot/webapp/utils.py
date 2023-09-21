import streamlit as st


def icon(emoji: str):
    """Shows an emoji as a Notion-style page icon."""
    st.write(
        f'<span style="font-size: 78px; line-height: 1">{emoji}</span>',
        unsafe_allow_html=True,
    )


def hide_streamlit_brandings():
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
