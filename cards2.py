import streamlit as st

page_title = "Shuttle Bot"
layout: str = "centered"
st.set_page_config(
    page_title=page_title,
    page_icon="🔖",
    layout=layout,
    initial_sidebar_state="collapsed",
)


def load_css_styles(file_path: str):
    with open(file_path, "r") as f:
        css = f.read()
    st.html(f"<style>{css}</style>")


load_css_styles("cards.css")


with st.popover("Advanced filters"):
    dates = st.date_input(label="Date you want to search for?")
    time = st.time_input(label="Time you want to search for?")


carousel_container = st.container()


with carousel_container:
    st.html(
        f"""
        <div class="horizontal-scroll">
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
            <div class="card">
            <div class="card-desc">
              <div class="card-location">Approx. 6.2 miles away</div>
              <div class="card-title">City Sports - City University of London</div>
              <div class="organisation">citysports.org.uk</div>
              <div class="card-date">2024-04-07 (Sunday)</div>
              <p class="recent">Slots starting at 18.00, 18.40</p>
              <button type="button" class="button">
                <a href="https://en.wikipedia.org/wiki/Hyperlink">Visit booking site</a>
              </button>
            </div>
          </div>
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
            <div class="card">
            <div class="card-desc">
              <div class="card-location">Approx. 6.2 miles away</div>
              <div class="card-title">City Sports - City University</div>
              <div class="organisation">citysports.org.uk</div>
              <div class="card-date">2024-04-07 (Sunday)</div>
              <p class="recent">Slots starting at 18.00, 18.40</p>
              <button type="button" class="button">
                <a href="https://en.wikipedia.org/wiki/Hyperlink">Visit booking site</a>
              </button>
            </div>
          </div>
        </div>
        """
    )

