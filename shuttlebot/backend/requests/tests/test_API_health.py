import httpx

def test_api_health():
    """Tests if API is healthy or not"""
    url = "https://better-admin.org.uk/api/activities/venues"
    headers = {
        "origin": "https://bookings.better.org.uk",
    }
    response = httpx.get(url, headers=headers)
    assert response.status_code == 200, "Expected status code to be 200, but it was:"
