# flask-beer
## Keeping brewery data fresh

The site ships with 2020 brewery data in `data/*.csv`, but live brewery
lookups go through the [Open Brewery DB](https://www.openbrewerydb.org/)
(free, no API key) via `brewery_api.py`.

To merge newly-opened NC breweries into your MongoDB, run the monthly sync:

    MONGO_URI="mongodb+srv://..." python sync.py

It only **inserts** breweries it hasn't seen before (keyed by `odb_id`) —
it never updates or deletes your existing data. Run it monthly by hand, or
as a Render cron job.

## Plan a Brewery Day

`/itinerary` is an interactive day-planner: search NC breweries, find nearby
breweries/restaurants/museums/parks, and build a stop-by-stop timeline with
drive times (via free OSRM routing) and tap-to-call phone numbers.
