"""Smoke tests for the brewery site's live-data features.

Run:  python -m pytest tests/   (or python -m unittest discover tests)
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MONGO_URI", "mongodb://test-dummy:27017/test")

# --- Stub MongoDB before app.py is imported (it seeds at import time). ---

import pymongo


class FakeCollection:
    def __init__(self):
        self.docs = []

    def count_documents(self, _filter):
        return len(self.docs)

    def insert_many(self, docs):
        self.docs.extend(docs)

    def find(self, *args, **kwargs):
        return list(self.docs)

    def update_one(self, filt, update, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filt.items()):
                return MagicMock(upserted_id=None)
        new_doc = dict(filt)
        new_doc.update(update.get("$setOnInsert", {}))
        self.docs.append(new_doc)
        return MagicMock(upserted_id="newid")


class FakeDB:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCollection())


class FakeClient:
    last_instance = None

    def __init__(self, uri):
        self.dbs = {}
        FakeClient.last_instance = self

    def __getitem__(self, name):
        return self.dbs.setdefault(name, FakeDB())


pymongo.MongoClient = FakeClient

import brewery_api  # noqa: E402
import sync  # noqa: E402
import app as app_module  # noqa: E402


SAMPLE_ODB = {
    "id": "abc-123",
    "name": "Trophy Brewing",
    "brewery_type": "micro",
    "street": "656 Maywood Ave",
    "address_1": "656 Maywood Ave",
    "city": "Raleigh",
    "state_province": "North Carolina",
    "postal_code": "27603",
    "phone": "9195551234",
    "website_url": "https://trophybrewing.com",
    "longitude": -78.646,
    "latitude": 35.771,
}


def _mock_resp(json_data):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestNormalize(unittest.TestCase):
    def test_full_record(self):
        n = brewery_api.normalize_odb(SAMPLE_ODB)
        self.assertEqual(n["odb_id"], "abc-123")
        self.assertEqual(n["name"], "Trophy Brewing")
        self.assertEqual(n["website_url"], "https://trophybrewing.com")
        self.assertTrue(brewery_api.has_coords(n))

    def test_null_coords(self):
        rec = dict(SAMPLE_ODB, latitude=None, longitude=None)
        n = brewery_api.normalize_odb(rec)
        self.assertFalse(brewery_api.has_coords(n))

    def test_missing_website(self):
        rec = dict(SAMPLE_ODB, website_url=None)
        self.assertIsNone(brewery_api.normalize_odb(rec)["website_url"])

    def test_formatters(self):
        self.assertEqual(brewery_api.format_duration(750), "12 min")
        self.assertEqual(brewery_api.format_duration(5400), "1 hr 30 min")
        self.assertEqual(brewery_api.format_distance(1609.344), "1.0 mi")
        self.assertIsNone(brewery_api.format_duration(None))


class TestOdbProxies(unittest.TestCase):
    @patch("brewery_api.requests.get")
    def test_search_breweries_url(self, mock_get):
        mock_get.return_value = _mock_resp([SAMPLE_ODB])
        out = brewery_api.search_breweries(page=2)
        args, kwargs = mock_get.call_args
        self.assertIn("openbrewerydb", args[0])
        self.assertEqual(kwargs["params"]["by_state"], "north_carolina")
        self.assertEqual(kwargs["params"]["page"], 2)
        self.assertEqual(out[0]["name"], "Trophy Brewing")

    @patch("brewery_api.requests.get")
    def test_find_brewery_filters_nc(self, mock_get):
        other = dict(SAMPLE_ODB, id="x", name="Trophy Clone", state_province="Virginia")
        mock_get.return_value = _mock_resp([SAMPLE_ODB, other])
        out = brewery_api.find_brewery("trophy")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "Trophy Brewing")

    @patch("brewery_api.requests.get")
    def test_nearby_skips_null_coords(self, mock_get):
        nocoords = dict(SAMPLE_ODB, id="y", latitude=None, longitude=None)
        mock_get.return_value = _mock_resp([SAMPLE_ODB, nocoords])
        out = brewery_api.nearby_breweries(35.78, -78.64)
        self.assertEqual(len(out), 1)


class TestOverpass(unittest.TestCase):
    @patch("brewery_api.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _mock_resp(
            {"elements": [
                {"lat": 35.78, "lon": -78.64,
                 "tags": {"name": "Taco Stand", "addr:street": "Main St",
                          "phone": "919-555-0000", "website": "https://tacos.example"}}
            ]}
        )
        places, warning = brewery_api.nearby_places(35.78, -78.64, "restaurants")
        self.assertIsNone(warning)
        self.assertEqual(places[0]["name"], "Taco Stand")
        self.assertEqual(places[0]["phone"], "919-555-0000")

    @patch("brewery_api.requests.get")
    def test_flaky_graceful(self, mock_get):
        import requests as rq
        mock_get.side_effect = rq.Timeout("slow")
        places, warning = brewery_api.nearby_places(35.78, -78.64, "museums")
        self.assertEqual(places, [])
        self.assertTrue(warning)

    def test_unknown_kind(self):
        places, warning = brewery_api.nearby_places(35.78, -78.64, "stadiums")
        self.assertEqual(places, [])
        self.assertTrue(warning)


class TestOsrm(unittest.TestCase):
    @patch("brewery_api.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _mock_resp(
            {"routes": [{"duration": 754.2, "distance": 4828.0}]})
        out = brewery_api.route_between(-78.64, 35.78, -78.63, 35.77)
        self.assertAlmostEqual(out["duration_s"], 754.2)
        self.assertAlmostEqual(out["distance_m"], 4828.0)

    @patch("brewery_api.requests.get")
    def test_failure_graceful(self, mock_get):
        import requests as rq
        mock_get.side_effect = rq.ConnectionError("down")
        out = brewery_api.route_between(-78.64, 35.78, -78.63, 35.77)
        self.assertIsNone(out["duration_s"])
        self.assertTrue(out["warning"])


class TestSync(unittest.TestCase):
    @patch("sync.search_breweries")
    def test_upsert_logic(self, mock_search):
        recs = [brewery_api.normalize_odb(dict(SAMPLE_ODB, id=f"id-{i}"))
                for i in range(3)]
        mock_search.side_effect = [recs, []]
        col = FakeCollection()
        inserted, skipped = sync.sync(col)
        self.assertEqual(inserted, 3)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(col.docs), 3)
        # second run: everything already present, nothing inserted, nothing deleted
        mock_search.side_effect = [recs, []]
        inserted2, skipped2 = sync.sync(col)
        self.assertEqual(inserted2, 0)
        self.assertEqual(skipped2, 3)
        self.assertEqual(len(col.docs), 3)

    def test_field_mapping(self):
        doc = sync.to_mongo_doc(brewery_api.normalize_odb(SAMPLE_ODB))
        self.assertEqual(doc["breweries"], "Trophy Brewing")
        self.assertEqual(doc["website"], "https://trophybrewing.com")
        self.assertEqual(doc["odb_id"], "abc-123")
        self.assertEqual(doc["latitude"], 35.771)


class TestEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_existing_routes_intact(self):
        for path in ["/", "/beerMap", "/itinerary"]:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)

    @patch("brewery_api.requests.get")
    def test_brewery_search(self, mock_get):
        mock_get.return_value = _mock_resp([SAMPLE_ODB])
        resp = self.client.get("/api/breweries/search?q=trophy")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()[0]["name"], "Trophy Brewing")

    def test_brewery_search_empty_q(self):
        self.assertEqual(self.client.get("/api/breweries/search").get_json(), [])

    @patch("brewery_api.requests.get")
    def test_nearby_places_overpass_down(self, mock_get):
        import requests as rq
        mock_get.side_effect = rq.Timeout("slow")
        resp = self.client.get("/api/nearby/places?lat=35.78&lng=-78.64&kind=restaurants")
        self.assertEqual(resp.status_code, 200)  # never a 500
        body = resp.get_json()
        self.assertEqual(body["places"], [])
        self.assertTrue(body["warning"])

    @patch("brewery_api.requests.get")
    def test_route_osrm_down(self, mock_get):
        import requests as rq
        mock_get.side_effect = rq.ConnectionError("down")
        resp = self.client.get("/api/route?from=-78.64,35.78&to=-78.63,35.77")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIsNone(body["duration_s"])
        self.assertIsNone(body["duration_text"])

    def test_route_bad_params(self):
        self.assertEqual(self.client.get("/api/route").status_code, 400)


if __name__ == "__main__":
    unittest.main()
