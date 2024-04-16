import streamlit as st

page_title = "Shuttle Bot"
layout: str = "centered"
st.set_page_config(
    page_title=page_title,
    layout=layout,
    initial_sidebar_state="collapsed",
)


@st.cache_data
def load_css_styles(file_path: str):
    with open(file_path, "r") as f:
        css = f.read()
    return css


cards_css = load_css_styles("shuttlebot/frontend/cards.css")
st.html(f"<style>{cards_css}</style>")

carousel_container = st.container()


def generate_carousal_with_data():
    card_html_template = f"""
    <div class="card">
    <div class="card-desc">
      <div class="card-location">Approx. 6.2 miles away</div>
      <div class="card-title">Tottenham Court Road and Covent Garden</div>
      <div class="organisation">better.org.uk</div>
      <div class="card-date">2024-04-07 (Sunday)</div>
      <p class="recent">Slots starting at 18.00, 18.40, 19.00 </p>
      <button type="button" class="button">
        <a href="https://en.wikipedia.org/wiki/Hyperlink">Visit booking site</a>
      </button>
    </div>
    </div>
    """
    for _ in range(3):
        card_html_template += card_html_template
    st.html(
        f"""
        <div class="horizontal-scroll">
          {card_html_template}
        </div>
        """
    )


with carousel_container:
    generate_carousal_with_data()

