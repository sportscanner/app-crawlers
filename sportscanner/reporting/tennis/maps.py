from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import folium

from typing import List, Optional
from pydantic import BaseModel


class IndoorCourt(BaseModel):
    label: str
    count: int


class OutdoorCourt(BaseModel):
    label: str
    count: int


class GeographicAreaName(BaseModel):
    en_GB: str


class GeographicArea(BaseModel):
    name: GeographicAreaName


class Location(BaseModel):
    addressLine1: str
    addressLine2: Optional[str]  # Allowing None values
    addressLine3: Optional[str]
    postcode: str
    coordinates: List[float]
    cityId: str
    city: GeographicArea
    placeId: str
    place: GeographicArea
    stateId: Optional[str]
    state: Optional[str]


class Court(BaseModel):
    _id: str
    name: str
    slug: str
    phone: Optional[str]  # Allowing None values
    courtType: Optional[str]  # Allowing None values
    privateCourt: Optional[bool]  # Allowing None values
    lights: bool
    indoorCourts: List[IndoorCourt]
    outdoorCourts: List[OutdoorCourt]
    resources: List
    bookingProvider: Optional[str]
    location: Location


class Data(BaseModel):
    courts: List[Court]


class RootModel(BaseModel):
    data: Data

import json
import glob  # To list multiple files
from pathlib import Path

# Define the dataset directory
dataset_dir = "datasets/spin-tennis"

# List all JSON files in the dataset directory
json_files = glob.glob(f"{dataset_dir}/*.json")

# Initialize an empty list to store merged courts
merged_courts = []

# Iterate over all JSON files and merge them
for file in json_files:
    with open(file, "r") as f:
        raw_data = json.load(f)
        merged_courts.extend(raw_data["data"]["courts"])  # Append courts from each file

# Create a unified dictionary following the expected RootModel structure
merged_data = {
    "data": {
        "courts": merged_courts
    }
}

# Validate and parse data using Pydantic
parsed_data = RootModel(**merged_data)
# Define colors
highlight_color = "blue"  # For courts with a booking provider
default_color = "gray"  # For courts without a booking provider

# Create a map centered on London
m = folium.Map(location=[51.5074, -0.1278], zoom_start=11, tiles="Cartodb Positron")

# Iterate over courts and add markers
for court in parsed_data.data.courts:
    lat, lon = court.location.coordinates[1], court.location.coordinates[0]
    color = highlight_color if court.bookingProvider else default_color

    popup_html = f"""
    <div style="width: 250px;">
        <b>{court.name}</b><br>
        <i>Type:</i> {court.courtType}<br>
        <i>Location:</i> {court.location.addressLine1}, {court.location.postcode}
    </div>
    """

    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(popup_html),
        icon=folium.Icon(color=color)
    ).add_to(m)

    # Add a light circle around the highlighted nodes
    if color == highlight_color:
        folium.Circle(
            location=[lat, lon],
            radius=1000,  # 1 mile in meters
            color="lightblue",
            fill=True,
            fill_color="lightblue",
            fill_opacity=0.2,  # Light transparency
            weight=1
        ).add_to(m)

# Save map to file
m.save("court_locations.html")
print("Map saved to court_locations.html")