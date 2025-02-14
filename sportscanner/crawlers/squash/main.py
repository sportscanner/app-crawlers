from typing import List, Optional
from pydantic import BaseModel, field_validator, ValidationError, RootModel
from datetime import datetime
import httpx
from typing import Optional
from rich import print

class Slot(BaseModel):
    startTime: str
    endTime: str
    price: float
    availability: Optional[int]

    @field_validator("startTime", "endTime")
    def validate_time_format(cls, value):
        try:
            datetime.strptime(value, "%H:%M:%S")
            return value
        except ValueError:
            raise ValueError("Incorrect time format, should be HH:MM:SS")


class Date(BaseModel):
    date: str
    slots: List[Slot]

    @field_validator("date")
    def validate_date_format(cls, value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            raise ValueError("Incorrect date format, should be YYYY-MM-DD")



class Location(BaseModel):
    location: str
    dates: List[Date]
    errors: List[str]


class Provider(BaseModel):
    provider: str
    locations: List[Location]


class Response(RootModel):
    root: List[Provider]


def fetch_and_validate_data(api_url: str, payload: dict) -> Optional[Response]:
    """Fetches data from the API with a payload and validates it using Pydantic."""
    try:
        with httpx.Client() as client:  # Use synchronous client
            response = client.post(api_url, json=payload)  # Use POST and send JSON payload
            response.raise_for_status()
            data = response.json()

            try:
                validated_response = Response(root=data)
                return validated_response
            except ValidationError as e:
                print(f"Validation Error: {e}")
                # Optionally, log the raw data and errors for debugging:
                # import json; print(json.dumps(data, indent=2))
                return None
            except Exception as e:
                print(f"An unexpected error occurred during validation: {e}")
                return None

    except httpx.HTTPError as e:
        print(f"HTTP Error: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during the API call: {e}")
        return None


def main():
    api_url = "https://backend.squashfinder.co.uk/api/availability"  # Replace with your actual API URL
    payload = {
      "startDate": "2025-02-13",
      "endDate": "2025-02-15",
      "locations": {
        "places": [
          "Epping",
          "Balham",
          "Tolworth",
          "Tooting"
        ],
        "better": [
          "canons-leisure-centre",
          "swiss-cottage-leisure-centre",
          "hammersmith-fitness-squash-centre",
          "finsbury-leisure-centre",
          "ironmonger-row-baths",
          "britannia-leisure-centre",
          "walthamstow-leisure-centre",
          "clissold-leisure-centre"
        ],
        "activeLambeth": [

        ],
        "everyoneActive": [
          "Harrow",
          "WestwayPortobello",
          "QueenMother"
        ]
      }
    }
    validated_data = fetch_and_validate_data(api_url, payload)
    print(validated_data)


if __name__ == "__main__":
    main()  # No asyncio needed for synchronous code


