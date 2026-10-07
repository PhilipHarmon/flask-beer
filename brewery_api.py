"""Server-side helpers for live brewery/places/routing data.

All third-party calls go through here so the frontend never needs API keys:

- Open Brewery DB (https://www.openbrewerydb.org/) — free, no key, CORS-open.
  Brewery names, types, addresses, phones, websites, coordinates.
- Overpass API (OpenStreetMap) — free, no key. Nearby restaurants, museums,
  parks. Flaky by nature: callers must treat failures as "no results".
- OSRM demo server — free, no key. Drive time/distance between two points.

No new environment variables are needed; the only secret in this project
remains MONGO_URI (see app.py).
"""
import requests

ODB_BASE = "https://api.openbrewerydb.org/v1/breweries"
OSRM_BASE = "https://router.project-osrm.org/route/v1/driving"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

HTTP_TIMEOUT = 8  # seconds; Overpass in particular can hang

NC_STATE = "north_carolina"


def _get_json(url, params=None, timeout=HTTP_TIMEOUT):
    """GET and parse JSON. Raises requests.RequestException on any failure."""
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def normalize_odb(record):
    """Map one Open Brewery DB record onto our clean brewery dict.

    Field mapping onto the existing Mongo `breweries` collection shape:
        name            -> breweries
        brewery_type    -> brewery_type
        city            -> city
        state_province  -> state
        latitude        -> latitude
        longitude       -> longitude
        phone           -> phone
        website_url     -> website
        id              -> odb_id        (dedupe key for the monthly sync)
        street/address_1-> street        (extra context)
        postal_code     -> postal_code   (extra context)
    """
    street = record.get("street") or record.get("address_1")
    return {
        "odb_id": record.get("id"),
        "name": record.get("name"),
        "brewery_type": record.get("brewery_type"),
        "street": street,
        "city": record.get("city"),
        "state": record.get("state_province") or record.get("state"),
        "postal_code": record.get("postal_code"),
        "phone": record.get("phone"),
        "website_url": record.get("website_url"),
        "longitude": record.get("longitude"),
        "latitude": record.get("latitude"),
    }


def has_coords(brewery):
    """True when a normalized brewery has usable map coordinates."""
    return brewery.get("latitude") is not None and brewery.get("longitude") is not None


def search_breweries(state=NC_STATE, page=1, per_page=200):
    """One page of breweries for a state, normalized. Empty list = no more pages."""
    records = _get_json(
        ODB_BASE, params={"by_state": state, "page": page, "per_page": per_page}
    )
    return [normalize_odb(r) for r in records]


def nearby_breweries(lat, lng, radius_m=10000, per_page=20):
    """Breweries near a point, closest first, normalized."""
    records = _get_json(
        ODB_BASE,
        params={"by_dist": f"{lat},{lng}", "dist": radius_m, "per_page": per_page},
    )
    return [normalize_odb(r) for r in records if has_coords(normalize_odb(r))]


def find_brewery(name, state=NC_STATE, limit=15):
    """Search breweries by name, restricted to the given state, normalized."""
    records = _get_json(ODB_BASE, params={"by_name": name, "per_page": 50})
    matches = []
    for record in records:
        norm = normalize_odb(record)
        state_val = (norm.get("state") or "").lower().replace(" ", "_")
        if state_val == state:
            matches.append(norm)
        if len(matches) >= limit:
            break
    return matches


# --- Nearby places (restaurants / museums / parks) via Overpass -------------

_PLACE_QUERIES = {
    "restaurants": '[amenity=restaurant]',
    "museums": '[tourism=museum]',
    "parks": '[leisure=park]',
}

_PLACE_KIND_LABEL = {
    "restaurants": "Restaurant",
    "museums": "Museum",
    "parks": "Park",
}


def nearby_places(lat, lng, kind, radius_m=2500, limit=20):
    """Places of `kind` near a point via the Overpass API.

    Returns (places, warning): places is a list of
    {name, kind, address, phone, website, lat, lng}; warning is None on
    success or a short human-readable note when the lookup failed.
    Never raises — Overpass is flaky, so failure means "no results".
    """
    if kind not in _PLACE_QUERIES:
        return [], f"Unknown place kind: {kind}"
    query = (
        f"[out:json][timeout:20];"
        f"node(around:{radius_m},{lat},{lng}){_PLACE_QUERIES[kind]};"
        f"out body {limit};"
    )
    try:
        data = _get_json(OVERPASS_URL, params={"data": query})
    except Exception:
        return [], "Nearby places are temporarily unavailable — try again in a bit."
    places = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        addr_parts = [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:city"),
        ]
        places.append(
            {
                "name": name,
                "kind": kind,
                "address": " ".join(p for p in addr_parts if p) or None,
                "phone": tags.get("phone"),
                "website": tags.get("website"),
                "lat": el.get("lat"),
                "lng": el.get("lon"),
            }
        )
        if len(places) >= limit:
            break
    return places, None


# --- Routing via OSRM --------------------------------------------------------


def route_between(from_lng, from_lat, to_lng, to_lat):
    """Drive time/distance between two points via OSRM.

    Returns {"duration_s", "distance_m"} or {"duration_s": None,
    "distance_m": None, "warning": ...} on failure. Never raises.
    """
    url = f"{OSRM_BASE}/{from_lng},{from_lat};{to_lng},{to_lat}"
    try:
        data = _get_json(url, params={"overview": "false"})
        route = (data.get("routes") or [{}])[0]
        return {
            "duration_s": route.get("duration"),
            "distance_m": route.get("distance"),
        }
    except Exception:
        return {
            "duration_s": None,
            "distance_m": None,
            "warning": "Drive time unavailable right now.",
        }


def format_duration(seconds):
    """67.5 minutes -> '1 hr 8 min'; None -> None."""
    if seconds is None:
        return None
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} hr {minutes} min" if minutes else f"{hours} hr"


def format_distance(meters):
    """4828.0 m -> '3.0 mi'; None -> None."""
    if meters is None:
        return None
    return f"{meters / 1609.344:.1f} mi"
