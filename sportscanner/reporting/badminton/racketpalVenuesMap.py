from pydantic import BaseModel
from typing import List, Optional
import folium
import json
import folium
import json
from sportscanner import schemas
from sportscanner.utils import get_sports_venue_mappings_from_raw
from rich import print
# Load sports venues data
sports_centres_mapping: schemas.SportsVenueMappingModel = get_sports_venue_mappings_from_raw(
    path="./sportscanner/venues.json",
)

# Initialize GeoJSON structure
geojson_data = {
    "type": "FeatureCollection",
    "features": []
}


# Define Pydantic models
class Coordinates(BaseModel):
    latitude: float
    longitude: float

class Court(BaseModel):
    sport: str

class Venue(BaseModel):
    _id: str
    type: str
    name: str
    deactivated: bool
    isPremium: bool
    isPrivate: bool
    courts: List[Court]
    isFavourite: bool
    address: str
    coordinates: Coordinates

class VenueList(BaseModel):
    venues: List[Venue]

with open("datasets/racketpal-badminton-london.json", "r") as f:
    raw_data = json.load(f)
    parsed_data = VenueList(venues=raw_data)

# Create a Folium map centered on the first venue
map_center = [parsed_data.venues[0].coordinates.latitude, parsed_data.venues[0].coordinates.longitude]
m = folium.Map(location=[51.5074, -0.1278], zoom_start=11, tiles="Cartodb Positron")

# Iterate through venues and add markers
for venue in parsed_data.venues:
    lat, lon = venue.coordinates.latitude, venue.coordinates.longitude

    # Create a popup with venue details
    popup_html = f"""
    <div style="width: 250px;">
        <b>{venue.name}</b><br>
        <i>Type:</i> {venue.type}<br>
        <i>Address:</i> {venue.address}<br>
        <i>Sports Available:</i> {", ".join(court.sport for court in venue.courts)}
    </div>
    """

    # Add a marker
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(popup_html),
        icon=folium.Icon(color="lightgray" if not venue.isPrivate else "red")  # Blue for public, Red for private
    ).add_to(m)

for organisation in sports_centres_mapping.root:
    for venue in organisation.venues:
        # Define popup content

        html = f"""
            <div style="width: 250px;">
                <b>{venue.venue_name}</b><br>
                <i>Type:</i> {organisation.organisation}<br>
                <i>Address:</i> {venue.location.address}<br>
            </div>
            """

        color = "blue"
        folium.Marker(
            location=[venue.location.latitude, venue.location.longitude],
            popup=folium.Popup(html),
            icon=folium.Icon(color=color)
        ).add_to(m)

        folium.Circle(
            location=[venue.location.latitude, venue.location.longitude],
            radius=2500,  # 1 mile in meters
            color="blue",
            fill=True,
            fill_color="lightblue",
            fill_opacity=0.2,  # Light transparency
            weight=0.2
        ).add_to(m)

# Save and display map
m.save("racketpal-badminton-venues-map.html")
print("Map saved to racketpal-badminton-venues-map.html")