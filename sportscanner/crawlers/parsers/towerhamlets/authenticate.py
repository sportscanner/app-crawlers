import time
from typing import Optional

from playwright.sync_api import sync_playwright
from rich import print


# Start Playwright in a headless browser context
def get_authorization_token() -> Optional[str]:
    """Returns bearer token needed to authenticate with BeWell servers"""
    with sync_playwright() as p:
        # Launch browser (use Chromium, Firefox, or Webkit)
        browser = p.chromium.launch(
            headless=True
        )  # headless=True makes the browser run in the background
        # Create a new browser page (tab)
        page = browser.new_page()
        # Navigate to the target website
        page.goto("https://towerhamletscouncil.gladstonego.cloud/book")
        # Wait for the page to load (you may need to adjust this depending on the site)
        time.sleep(1)
        # Fetch the token from localStorage
        token: Optional[str] = page.evaluate(
            "window.localStorage.getItem('token');"
        )  # Correct syntax
        browser.close()
        return f"Bearer {token}"


if __name__ == "__main__":
    print(get_authorization_token())
