"""Monthly sync: pull fresh NC brewery data from Open Brewery DB into MongoDB.

Usage:
    MONGO_URI="mongodb+srv://..." python sync.py

Behavior:
- Paginates Open Brewery DB for ALL North Carolina breweries
  (per_page=200 until an empty page comes back).
- Upserts into the `breweries` collection keyed by `odb_id`.
- ONLY INSERTS new breweries. Never updates, never deletes — your existing
  data is never touched or overwritten.

Run it monthly (a Render cron job, or by hand) to keep the site current
between code deploys.
"""
import os
import sys

from pymongo import MongoClient

from brewery_api import normalize_odb, search_breweries

MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    sys.exit("Error: MONGO_URI environment variable is not set.")

DB_NAME = os.environ.get("MONGO_DB_NAME", "nc_craft_breweries")

# ODB -> Mongo `breweries` field mapping (keeps the shape the existing
# templates and /geoData expect):
#   name            -> breweries
#   brewery_type    -> brewery_type
#   city            -> city
#   state_province  -> state
#   latitude        -> latitude
#   longitude       -> longitude
#   phone           -> phone
#   website_url     -> website
#   id              -> odb_id        (dedupe key)
#   street          -> street
#   postal_code     -> postal_code


def to_mongo_doc(normalized):
    """Map a normalized ODB brewery onto the `breweries` collection shape."""
    return {
        "breweries": normalized.get("name"),
        "brewery_type": normalized.get("brewery_type"),
        "city": normalized.get("city"),
        "state": normalized.get("state"),
        "latitude": normalized.get("latitude"),
        "longitude": normalized.get("longitude"),
        "phone": normalized.get("phone"),
        "website": normalized.get("website_url"),
        "odb_id": normalized.get("odb_id"),
        "street": normalized.get("street"),
        "postal_code": normalized.get("postal_code"),
    }


def sync(collection):
    """Insert every NC brewery from ODB that isn't already stored.

    Returns (inserted, skipped).
    """
    inserted = 0
    skipped = 0
    page = 1
    while True:
        breweries = search_breweries(page=page)
        if not breweries:
            break
        for brewery in breweries:
            if not brewery.get("odb_id"):
                skipped += 1
                continue
            result = collection.update_one(
                {"odb_id": brewery["odb_id"]},
                {"$setOnInsert": to_mongo_doc(brewery)},
                upsert=True,
            )
            if result.upserted_id is not None:
                inserted += 1
            else:
                skipped += 1
        page += 1
    return inserted, skipped


def main():
    client = MongoClient(MONGO_URI)
    collection = client[DB_NAME]["breweries"]
    print("Syncing NC breweries from Open Brewery DB...")
    inserted, skipped = sync(collection)
    print(f"Done: {inserted} new breweries added, {skipped} already present.")


if __name__ == "__main__":
    main()
