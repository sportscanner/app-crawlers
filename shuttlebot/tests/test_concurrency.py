import httpx
import itertools
import json
from datetime import date, datetime, timedelta
from typing import List, Dict
import pandas as pd
import time
import asyncio
import pytest
import time
import requests

api_runtimes = []
async def fetch_data(client, url):
    print(url)
    tic = time.perf_counter()
    response = await client.get(url)
    tac = time.perf_counter()
    print(f"Time taken for single API call: {float(tac-tic)}")
    api_runtimes.append(float(tac-tic))
    return response

def generate_api_call_params():
    """Generates URL, Headers and Payload information for the API curl request"""
    url = (
        f"https://catfact.ninja/fact/"
    )
    headers = {}
    payload = {}
    return url, headers, payload

async def main():
    tic = time.perf_counter()
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = []  
        for _ in range(1000):
            url, headers, _ = generate_api_call_params()
            tasks.append(
                fetch_data(client, url)
            )
        results = await asyncio.gather(*tasks)
        results = [result.json() for result in results if result.status_code == 200]
        tac = time.perf_counter()
        print(f"Overall Time taken: {tac-tic}")
    

@pytest.mark.asyncio
@pytest.mark.skip(reason="no way of currently testing this")
def test_async_functionality():    
    # Act
    tic = time.perf_counter()
    asyncio.run(main())
    tac = time.perf_counter()
    overall_runtime = tac - tic

    sorted_api_runtimes = sorted(api_runtimes)
    # Assert
    assert overall_runtime < sorted_api_runtimes[-1] + sorted_api_runtimes[-2]


@pytest.mark.skip(reason="no way of currently testing this")
def test_api_health():
    """Tests if API is healthy or not"""
    response = requests.get("https://catfact.ninja/fact/")
    assert response.status_code == 200, "Expected status code to be 200, but it was:"

if __name__ == "__main__":
    asyncio.run(main())