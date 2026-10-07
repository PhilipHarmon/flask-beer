"""NC Craft Breweries — Flask app.

A website featuring the craft breweries of North Carolina, with D3/Leaflet
visualizations backed by MongoDB Atlas.

Configuration comes from environment variables — nothing secret lives in
this repo.

Required env vars:
    MONGO_URI      full MongoDB Atlas connection string (mongodb+srv://...)

Optional env vars:
    MONGO_DB_NAME  database name (default: nc_craft_breweries)
    PORT           port for local dev (default: 5000)
"""
import os

import pandas as pd
from flask import Flask, jsonify, render_template, request
from pymongo import MongoClient

import brewery_api

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI environment variable is not set.")

DB_NAME = os.environ.get("MONGO_DB_NAME", "nc_craft_breweries")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]


def seed_collection(collection_name, csv_file):
    """Load a CSV into MongoDB only if the collection is empty.

    Never drops or overwrites existing data — safe to run on every boot.
    Returns the number of documents inserted.
    """
    collection = db[collection_name]
    if collection.count_documents({}) > 0:
        return 0
    df = pd.read_csv(os.path.join(DATA_DIR, csv_file))
    docs = df.to_dict("records")
    if docs:
        collection.insert_many(docs)
    return len(docs)


# Seed from the bundled CSVs on startup. Existing data is left untouched,
# so this is a no-op once the database is populated.
seed_collection("beer_master", "master_beer_df.csv")
seed_collection("master_condensed", "master_beer_condensed.csv")
seed_collection("breweries", "nc_breweries_df.csv")
seed_collection("breweries_condensed", "satallite_breweries_removed.csv")


app = Flask(__name__)


@app.route("/")
def main():
    return render_template("index.html")


@app.route("/beerList")
def beer_list():
    master = list(db.master_condensed.find({}, {"_id": False}))
    breweries = list(db.breweries_condensed.find({}, {"_id": False}))
    return render_template("beerList.html", master=master, breweries=breweries)


@app.route("/beerMap")
def beer_map():
    return render_template("beerMap.html")


@app.route("/geoData")
def geo_data():
    breweries = list(db.breweries.find({}, {"_id": False}))
    features = []
    for brewery in breweries:
        brewery.pop("phone", None)  # keep phone numbers out of the GeoJSON
        features.append(
            {
                "type": "Feature",
                "properties": brewery,
                "geometry": {
                    "type": "Point",
                    "coordinates": [brewery["longitude"], brewery["latitude"]],
                },
            }
        )
    return jsonify({"type": "FeatureCollection", "features": features})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


# --- Live brewery data (Open Brewery DB, proxied so no keys leak) -----------


@app.route("/itinerary")
def itinerary():
    return render_template("itinerary.html")


@app.route("/api/breweries/search")
def api_brewery_search():
    """Search NC breweries by name. ?q=<name>"""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify([])
    try:
        return jsonify(brewery_api.find_brewery(query))
    except Exception as exc:
        return jsonify({"error": f"Brewery search failed: {exc}"}), 502


@app.route("/api/nearby/breweries")
def api_nearby_breweries():
    """Breweries near a point. ?lat=&lng=&radius_m= (default 10000)."""
    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "lat and lng query params are required."}), 400
    radius_m = request.args.get("radius_m", default=10000, type=int)
    try:
        return jsonify(brewery_api.nearby_breweries(lat, lng, radius_m=radius_m))
    except Exception as exc:
        return jsonify({"error": f"Nearby brewery lookup failed: {exc}"}), 502


@app.route("/api/nearby/places")
def api_nearby_places():
    """Nearby restaurants/museums/parks via Overpass. ?lat=&lng=&kind=.

    Never 500s: on failure returns {"places": [], "warning": "..."}.
    """
    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"places": [], "warning": "lat and lng query params are required."})
    kind = request.args.get("kind", "restaurants")
    radius_m = request.args.get("radius_m", default=2500, type=int)
    places, warning = brewery_api.nearby_places(lat, lng, kind, radius_m=radius_m)
    return jsonify({"places": places, "warning": warning})


@app.route("/api/route")
def api_route():
    """Drive time/distance between two points. ?from=LNG,LAT&to=LNG,LAT.

    Degrades gracefully: drive-time fields are null with a warning on failure.
    """
    try:
        from_lng, from_lat = (float(x) for x in request.args["from"].split(","))
        to_lng, to_lat = (float(x) for x in request.args["to"].split(","))
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "from and to query params as LNG,LAT are required."}), 400
    result = brewery_api.route_between(from_lng, from_lat, to_lng, to_lat)
    result["duration_text"] = brewery_api.format_duration(result.get("duration_s"))
    result["distance_text"] = brewery_api.format_distance(result.get("distance_m"))
    return jsonify(result)
