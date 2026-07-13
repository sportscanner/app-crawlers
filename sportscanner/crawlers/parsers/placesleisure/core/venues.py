"""
Places Leisure venue -> siteId mapping.

siteId is read off the `<input id="site-id" value="...">` element embedded in
each centre's own page (e.g. https://www.placesleisure.org/centres/{slug}/).
Unlike Matchi/Playtomic's facility/tenant ID maps, activity IDs are NOT
hardcoded here - they're discovered fresh on every crawl by parsing the
centre page's embedded schedule (see core/strategy.py), since venues expose
multiple, inconsistent activity IDs for the same sport (e.g. Tolworth has 4
separate badminton activity IDs) that don't follow a derivable pattern from
siteId, and hardcoding them risks silently going stale.

To add a new venue: visit its centre page, confirm `"ag":"BADMINTON"` or
`"ag":"PICKLEBALL"` session entries exist in the page source, and read
site-id from the page.
"""
from typing import Dict

SLUG_TO_SITE_ID: Dict[str, str] = {
    "chessington-sports-centre": "231",
    "battersea-sports-centre": "229",
    "roehampton-sports-and-fitness-centre": "18",
    "latchmere-leisure-centre": "13",
    "malden-centre": "98",
    "tolworth-recreation-centre": "33",
    "tooting-leisure-centre": "15",
    "wandle-recreation-centre": "16",
}
