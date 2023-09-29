import streamlit as st

# Define the carousel items (each item is a tuple with background color and multiline text)
carousel_items = [
    ("#FDF7F7", "<b>Line 1 Text for Card 1</b><br><i>Line 2 Text for Card 1</i>"),
    ("#FDF7F7", "<b>Line 1 Text for Card 2</b><br><i>Line 2 Text for Card 2</i>"),
    ("#FDF7F7", "<b>Line 1 Text for Card 3</b><br><i>Line 2 Text for Card 3</i>"),
    ("#FDF7F7", "<b>Line 1 Text for Card 4</b><br><i>Line 2 Text for Card 4</i>"),
]

# Create a container to hold the carousel
carousel_container = st.container()

# Add custom CSS for horizontal scrolling and card styling
st.markdown(
    f"""
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
    }}
    </style>
    """,
    unsafe_allow_html=True,  # Render the HTML content
)

# Create the horizontal card carousel
with carousel_container:
    st.markdown(
        f"""
        <div class="horizontal-scroll">
            {" ".join(f'<div class="card" style="background-color: {bg_color};">{text}</div>' for bg_color, text in carousel_items)}
        </div>
        """,
        unsafe_allow_html=True,  # Render the HTML content
    )
