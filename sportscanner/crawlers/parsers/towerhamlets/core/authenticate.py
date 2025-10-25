import asyncio
from playwright.async_api import async_playwright
from typing import Optional
import time
from playwright.sync_api import sync_playwright
from sportscanner.logger import logging


def get_authorization_token() -> Optional[str]:
    """Returns bearer token needed to authenticate with BeWell servers"""
    with sync_playwright() as p:
        # Launch browser (use Chromium, Firefox, or Webkit)
        browser = p.chromium.launch(
            headless=True, args=["--ignore-certificate-errors"]
        )  # headless=True makes the browser run in the background
        # Create a new browser page (tab)
        page = browser.new_page(ignore_https_errors=True)
        # Navigate to the target website
        page.goto("https://towerhamletscouncil.gladstonego.cloud/book")
        # Wait for the page to load (you may need to adjust this depending on the site)
        time.sleep(3)

        # Get cookies from the current browser context
        cookies = page.context.cookies()
        jwt_cookie = next((c["value"] for c in cookies if c["name"].lower() == "jwt"), None)

        browser.close()

        if jwt_cookie:
            logging.success(f"Extracted JWT cookie for TowerHamlets website: {jwt_cookie}")
            return jwt_cookie
        else:
            logging.error("JWT cookie not found")
            return None

if __name__ == "__main__":
    print(get_authorization_token())
