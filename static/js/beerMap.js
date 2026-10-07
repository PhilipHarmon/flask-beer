var map = L.map('map', {
    center: [35.78, -78.64],
    zoom: 18
});

// Free CARTO basemap (no API key needed).
L.tileLayer('https://cartodb-basemaps-{s}.global.ssl.fastly.net/light_all/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attribution">CARTO</a>'
}).addTo(map);

function websiteUrl(raw) {
    if (!raw) return null;
    var url = String(raw).trim();
    if (!url) return null;
    if (!/^https?:\/\//i.test(url)) url = "https://" + url;
    return url;
}

var customLayer = L.geoJson(null, {
    onEachFeature: function(feature, layer) {
        var props = feature.properties || {};
        var name = props.breweries || "Brewery";
        var city = props.city || "";
        var type = props.brewery_type || "";
        var site = websiteUrl(props.website);

        // Hover tooltip with the quick facts.
        layer.bindTooltip(
            "<strong>" + name + "</strong>" +
            (city ? "<br>" + city : "") +
            (type ? "<br><em>" + type + "</em>" : ""),
            { sticky: true }
        );

        // Click opens the brewery's website in a new tab (when known).
        layer.on("click", function() {
            if (site) window.open(site, "_blank", "noopener");
        });

        layer.bindPopup("<h3>" + name + "<h3><h3>Type of Brewery: " + type + '<h3>' +
            (site ? '<a href="' + site + '" target="_blank" rel="noopener">' + site + "</a></h3>"
                  : "<em>No website listed</em></h3>"));
    }
});


//var points = omnivore.csv('/data/nc_breweries_df.csv', null, customLayer);
//var blah = []
//brew_list.forEach(js => {
//   var outGeoJson = {}
//   outGeoJson['properties'] = js
//   outGeoJson['type']= "Feature"
//   outGeoJson['geometry']= {"type": "Point", "coordinates":
//     [js['latitude'], js['longitude']]}
//   blah.push(outGeoJson)
// })

// var pleaseWork = {"type": "FeatureCollection", "features": blah};

var points = omnivore.geojson("/geoData", null, customLayer);
//points.addTo(map);

var markers = L.markerClusterGroup({
    showCoverageOnHover: false
});

map.addLayer(markers);

points.on('ready', function() {
    map.fitBounds(points.getBounds())
    console.log(points.getLayers().length)
    markers.addLayer(points);
});
