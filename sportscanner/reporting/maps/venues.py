import folium
import json
from sportscanner import schemas
from sportscanner.utils import get_sports_venue_mappings_from_raw
from rich import print
# Load sports venues data
sports_centres_mapping: schemas.SportsVenueMappingModel = get_sports_venue_mappings_from_raw(
    path="./sportscanner/futures.json",
)

# Define colors for each organization
org_colors = {
    "https://www.better.org.uk": "green",
    "https://be-well.org.uk/": "blue",
    "https://citysport.org.uk": "red",
    "https://active.lambeth.gov.uk/": "black",
    "https://schoolhire.co.uk/": "lightgray",
    "https://www.lamptonleisure.co.uk/": "pink"
}

# Create a map centered on London
m = folium.Map(location=[51.5074, -0.1278], zoom_start=11, tiles="Cartodb Positron")

# Initialize GeoJSON structure
geojson_data = {
    "type": "FeatureCollection",
    "features": []
}


TOTAL_VENUES = 0
for organisation in sports_centres_mapping.root:
    for venue in organisation.venues:
        # Define popup content
        html = f"""
            <div style="width: 250px; white-space: nowrap;">
                <b>{venue.venue_name}</b><br>
                <span style="color: #666;">Organisation: {organisation.organisation}</span>
            </div>
            """

        color = org_colors.get(organisation.organisation_website, "gray")

        # Add marker to Folium map
        folium.Marker(
            location=[venue.location.latitude, venue.location.longitude],
            popup=folium.Popup(html),
            icon=folium.Icon(color=color)
        ).add_to(m)
        TOTAL_VENUES += 1
        # Add venue to GeoJSON data
        geojson_data["features"].append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [venue.location.longitude, venue.location.latitude]
            },
            "properties": {
                "venue_name": venue.venue_name,
                "organisation": organisation.organisation,
                "organisation_website": organisation.organisation_website,
                "color": color,
                "marker-color": color
            }
        })

# Save the map as an HTML file
m.save("datasets/reports/venues.html")

# Save GeoJSON file
geojson_filename = "datasets/reports/venues.geojson"
with open(geojson_filename, "w") as f:
    json.dump(geojson_data, f, indent=4)

print(
    {
        "venues": TOTAL_VENUES,
        "html": "datasets/reports/venues.html",
        "geojson": geojson_filename
    }
)

