from rich import print

import asyncio
from typing import Optional
from playwright.async_api import async_playwright


async def get_authorization_token() -> Optional[str]:
    """Returns bearer token needed to authenticate with BeWell servers using async Playwright"""
    async with async_playwright() as p:
        # Launch browser (use Chromium, Firefox, or WebKit)
        browser = await p.chromium.launch(headless=True)  # ✅ Use `await`
        page = await browser.new_page()  # ✅ Use `await`
        await page.goto("https://towerhamletscouncil.gladstonego.cloud/book")  # ✅ Use `await`

        await asyncio.sleep(1)  # ✅ Use `asyncio.sleep` instead of `time.sleep`

        # Fetch the token from localStorage
        token: Optional[str] = await page.evaluate("window.localStorage.getItem('token');")  # ✅ Use `await`
        await browser.close()  # ✅ Use `await`

        return f"Bearer {token}"

if __name__ == "__main__":
    print(
        get_authorization_token()
    )