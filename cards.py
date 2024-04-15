import streamlit as st


def custom_css_carousal():
    css_style = f"""
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
            background-color: #FAFAFA;
            white-space: pre-wrap;
            display: flex; /* Consider using flexbox for layout */
            flex-direction: column;
            padding: 10px;
            border: 1px solid #ccc;
            margin-right: 10px; /* Adjust for spacing */
            width: 200px; /* Set a fixed width */
            border-radius: 10px; /* Adjust the radius as needed */
            display: flex;
        flex-wrap: wrap;
        justify-content: space-between;

        }}
        .card span {{
            color: #6d7e86;
        }}
        .card strong {{
            font-weight: bold;
        }}
        .card-content {{  /* New class for card body content */
            flex: 1;  /* Allow content to fill remaining space */
        }}
        .card button {{
          padding: 8px 25px;
          display: block;
          margin: auto;
          border-radius: 8px;
          border: none;
          margin-top: 30px;
          background: #e8e8e8;
          color: #111111;
          font-weight: 600;
          text-decoration: none;  /* Remove underline */
        }}
        
        .card button:hover {{
          background: #212121;
          color: #ffffff;
        }}
        </style>
        """
    st.markdown(
        css_style,
        unsafe_allow_html=True,  # Render the HTML content
    )

custom_css_carousal()


carousel_items = []

carousel_items.append(
                (
                    "#FAFAFA",
                    f"<div style='white-space: pre-wrap;'><span style='color:#6d7e86'>Approx. miles away</span></div>"
                    f"<div style='white-space: pre-wrap;'>Yasir Khalid</div>"
                    f"<div style='white-space: pre-wrap;'><strong>18-11-1997</strong></div><br>"
                    f"<div style='white-space: pre-wrap;'>Slots starting at 8.00</div>",
                )
            )

carousel_items.append(
                (
                    "#FAFAFA",
                    f"<div style='white-space: pre-wrap;'><span style='color:#6d7e86'>Approx. miles away</span></div>"
                    f"<div style='white-space: pre-wrap;'>Hamza Khalid</div>"
                    f"<div style='white-space: pre-wrap;'><strong>18-11-1990</strong></div><br>"
                    f"<div style='white-space: pre-wrap;'>Slots starting at 8.00, 9.00, "
                    f"10.00, 11.00</div>",
                )
            )

carousel_container = st.container()

button_html = '<button><a href="https://en.wikipedia.org/wiki/Hyperlink">Visit Link</a></button>'


def create_card(bg_color, text):
    card_content = f"""
        <div class="card" style="background-color: {bg_color};">
        <div class="card-content">
                {text}
                </div>
                {button_html}
        </div>
    """
    return card_content


with carousel_container:
    st.markdown(
        f"""
        <div class="horizontal-scroll">
            {" ".join(create_card(bg_color, text) for bg_color, text in carousel_items)}
        </div>
        """,
        unsafe_allow_html=True
    )

