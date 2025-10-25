import geopy.distance
from sportscanner.logger import logging

def calculate_distance_in_miles(
    locationA: tuple[float, float], locationB: tuple[float, float]
) -> float:
    """calculate distance between 2 geolocations in miles"""
    distance = geopy.distance.distance(locationA, locationB)
    return round(distance.miles, 2)
