import httpx

def test_api_health():
    """Tests if API is healthy or not"""
    url = "https://better-admin.org.uk/api/activities/venues"
    headers = {
        "authority": "better-admin.org.uk",
        "accept": "application/json",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "origin": "https://bookings.better.org.uk",
        "referer": "https://bookings.better.org.uk/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
    }
    response = httpx.get(url, headers=headers)
    assert response.status_code == 200, "Expected status code to be 200, but it was:"
