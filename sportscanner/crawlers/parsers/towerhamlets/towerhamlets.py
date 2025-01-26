import time

from playwright.sync_api import sync_playwright

# Start Playwright in a headless browser context
with sync_playwright() as p:
    # Launch browser (use Chromium, Firefox, or Webkit)
    browser = p.chromium.launch(
        headless=True
    )  # headless=True makes the browser run in the background

    # Create a new browser page (tab)
    page = browser.new_page()

    # Navigate to the target website
    page.goto(
        "https://towerhamletscouncil.gladstonego.cloud/book"
    )  # Replace with the actual URL

    # Wait for the page to load (you may need to adjust this depending on the site)
    time.sleep(1)

    # Fetch the token from localStorage
    token = page.evaluate("window.localStorage.getItem('token');")  # Correct syntax
    # Print the token
    print(f"Token: {token}")

    # Close the browser
    browser.close()
