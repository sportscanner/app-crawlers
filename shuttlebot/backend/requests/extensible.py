"""Aim is to have a data fetcher class that is extensible for different API providers but collects and sends out all requests in Async manner"""

from abc import ABC, abstractmethod
from typing import Dict
import asyncio

class RequestsProcessingFramework(ABC):
    @abstractmethod
    async def fetch_data(self, url: str) -> Dict:
        pass

class SampleParser(RequestsProcessingFramework):
    async def fetch_data(client, url, headers):
        """Initiates request to server asynchronous using httpx"""
        response = await client.get(url, headers=headers)
        content_type = response.headers.get("content-type", "")
        return response.json()

class AnotherParser(RequestsProcessingFramework):
    async def fetch_data(self, url: str) -> Dict:
        # Implement the specific logic for fetching data using this parser
        # You can use asyncio.sleep() to simulate asynchronous processing
        await asyncio.sleep(2)
        return {"data": "parsed data from AnotherParser"}

class RequestsPipeline():
    def __init__(self):
        self.parsers = []
    
    def add_parser(self, parser: RequestsProcessingFramework):
        self.parsers.append(parser)
    
    async def process(self, url: str) -> Dict:
        tasks = [parser.fetch_data(url) for parser in self.parsers]
        results = await asyncio.gather(*tasks)
        return results

# Usage
async def main():
    pipeline = RequestsPipeline()
    pipeline.add_parser(SampleParser())
    pipeline.add_parser(AnotherParser())
    
    url = "https://example.com"
    results = await pipeline.process(url)
    print(results)

# Run the event loop
asyncio.run(main())
