import geopy.distance
from loguru import logger as logging

from external.routers.geolocation.api import (
    get_postcode_metadata,
    validate_uk_postcode,
)

# Define the coordinates of the two places
place1 = (37.783333, -122.416667)  # San Francisco, CA
place2 = (40.712778, -74.005957)  # New York, NY


def calculate_distance_in_miles(
    locationA: tuple[float, float], locationB: tuple[float, float]
) -> float:
    """calculate distance between 2 geolocations in miles"""
    distance = geopy.distance.distance(locationA, locationB)
    return round(distance.miles, 2)


if __name__ == "__main__":
    postcodeA, postcodeB = "SE2 9QQ", "E14 4PA"
    if validate_uk_postcode(postcodeA) and validate_uk_postcode(postcodeB):
        postcodeA_metadata = get_postcode_metadata(postcodeA)
        postcodeB_coordinates = (51.5049, -0.061617)
        dist = calculate_distance_in_miles(
            locationA=(
                postcodeA_metadata.result.longitude,
                postcodeA_metadata.result.latitude,
            ),
            locationB=postcodeB_coordinates,
        )

        logging.success(
            f"Calculated distance between {postcodeA} and {postcodeB} = {dist}"
        )
