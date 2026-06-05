import csv
import io
import re

import requests
from flask import Flask, Response, render_template_string, request
from openpyxl import Workbook

app = Flask(__name__)

ADDRESS_URL = "https://gcgis.guilfordcountync.gov/arcgis/rest/services/SiteStructureAddressPoints/FeatureServer/0/query"
PARCEL_URL = "https://gcgis.guilfordcountync.gov/arcgis/rest/services/Hosted/Parcel_Boundaries/FeatureServer/0/query"

HTML = """
<!doctype html>
<html>
<head>
    <title>Doors | Adalia Works</title>
    <link rel="icon" href="data:,">
    <style>
        body { font-family: Arial, sans-serif; max-width: 900px; margin: 50px auto; padding: 20px; }
        h1 { margin-bottom: 5px; }
        .subtitle { color: #666; margin-bottom: 30px; }
        input, button { width: 100%; padding: 10px; margin-top: 8px; margin-bottom: 20px; font-size: 16px; box-sizing: border-box; }
        button { cursor: pointer; }
        .button-row { display: flex; gap: 10px; }
        .button-row button { flex: 1; }
        .results { margin-top: 30px; padding: 20px; border: 1px solid #ddd; background: #fafafa; }
        textarea { width: 100%; height: 300px; font-size: 14px; padding: 10px; box-sizing: border-box; }
        footer { margin-top: 60px; padding-top: 20px; border-top: 1px solid #ddd; text-align: center; color: #666; font-size: 14px; }
        footer a { color: #666; text-decoration: none; }
        footer a:hover { text-decoration: underline; }
        footer small { display: block; margin-top: 6px; color: #888; }
    </style>
</head>
<body>
    <h1>Doors</h1>
    <div class="subtitle">Powered by Guilford County GIS</div>

    <form method="post" action="/">
        <label>Street Name(s)</label>
        <input type="text" name="streets" placeholder="Woodland Drive, Elm Street" value="{{ streets_raw }}" required>

        <label>ZIP Code(s) — optional</label>
        <input type="text" name="zip_codes" placeholder="Optional: 27408, 27410" value="{{ zip_codes_raw }}">

        <button type="submit">Preview Addresses</button>
    </form>

    {% if searched %}
        <div class="results">
            <h2>{{ rows|length }} Addresses Found</h2>

            {% if rows %}
                <div class="button-row">
                    <form method="post" action="/download">
                        <input type="hidden" name="streets" value="{{ streets_raw }}">
                        <input type="hidden" name="zip_codes" value="{{ zip_codes_raw }}">
                        <input type="hidden" name="format" value="csv">
                        <button type="submit">Download CSV</button>
                    </form>

                    <form method="post" action="/download">
                        <input type="hidden" name="streets" value="{{ streets_raw }}">
                        <input type="hidden" name="zip_codes" value="{{ zip_codes_raw }}">
                        <input type="hidden" name="format" value="xlsx">
                        <button type="submit">Download Excel</button>
                    </form>

                    <button type="button" onclick="copyAddresses()">Copy Addresses</button>
                </div>

                <textarea id="addressBox" readonly>full_address,owner_name
{% for row in rows %}{{ row.full_address }},{{ row.owner_name }}
{% endfor %}</textarea>
            {% else %}
                <p>No matching addresses found.</p>
            {% endif %}
        </div>
    {% endif %}

    <footer>
        &copy; Adalia Works |
        <a href="https://adaliaworks.com" target="_blank" rel="noopener noreferrer">adaliaworks.com</a>
        <small>Doors v0.6</small>
    </footer>

    <script>
        function copyAddresses() {
            const box = document.getElementById("addressBox");
            box.select();
            box.setSelectionRange(0, 999999);
            navigator.clipboard.writeText(box.value);
        }
    </script>
</body>
</html>
"""


def natural_sort_key(value):
    return [
        int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(value))
    ]


def split_street(street):
    parts = street.strip().split()
    street_types = {
        "street",
        "st",
        "drive",
        "dr",
        "road",
        "rd",
        "avenue",
        "ave",
        "lane",
        "ln",
        "court",
        "ct",
        "circle",
        "cir",
        "place",
        "pl",
        "boulevard",
        "blvd",
        "way",
        "trail",
        "trl",
        "parkway",
        "pkwy",
        "terrace",
        "ter",
        "loop",
        "pass",
        "alley",
        "aly",
    }

    if len(parts) > 1 and parts[-1].lower() in street_types:
        return " ".join(parts[:-1]), parts[-1]

    return street.strip(), ""


def normalize_type(st_type):
    mapping = {
        "dr": "Drive",
        "drive": "Drive",
        "st": "Street",
        "street": "Street",
        "rd": "Road",
        "road": "Road",
        "ave": "Avenue",
        "avenue": "Avenue",
        "ln": "Lane",
        "lane": "Lane",
        "ct": "Court",
        "court": "Court",
        "cir": "Circle",
        "circle": "Circle",
        "pl": "Place",
        "place": "Place",
        "blvd": "Boulevard",
        "boulevard": "Boulevard",
        "way": "Way",
        "trl": "Trail",
        "trail": "Trail",
        "pkwy": "Parkway",
        "parkway": "Parkway",
        "ter": "Terrace",
        "terrace": "Terrace",
        "loop": "Loop",
        "pass": "Pass",
        "aly": "Alley",
        "alley": "Alley",
    }
    return mapping.get(st_type.lower(), st_type.title())


def sql_escape(value):
    return value.replace("'", "''")


def parse_list(raw):
    return [item.strip() for item in raw.split(",") if item.strip()]


def fetch_owner_name_from_point(x, y):
    if x is None or y is None:
        return ""

    params = {
        "geometry": f"{x},{y}",
        "geometryType": "esriGeometryPoint",
        "inSR": "2264",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "reid",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": 1,
    }

    try:
        response = requests.get(PARCEL_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        features = data.get("features", [])
        if not features:
            return ""

        attrs = features[0].get("attributes", {})
        reid = attrs.get("reid", "")

        # Owner-name lookup can be added here once we confirm the public tax-data endpoint/field names.
        # For now, return the REID as a useful parcel reference if owner is unavailable.
        return f"REID {reid}" if reid else ""

    except Exception:
        return ""


def fetch_addresses_for_street_zip(street, zip_code=None):
    street_name, street_type = split_street(street)

    if street_type:
        street_type = normalize_type(street_type)

    where = f"UPPER(St_Name) = '{sql_escape(street_name.upper())}'"

    if street_type:
        where += f" AND St_PosTyp = '{sql_escape(street_type)}'"

    if zip_code:
        where += f" AND Post_Code = '{sql_escape(zip_code)}'"

    params = {
        "where": where,
        "outFields": "Add_Number,St_Name,St_PosTyp,Post_Code,FullAddress",
        "returnGeometry": "true",
        "outSR": "2264",
        "f": "json",
        "resultRecordCount": 2000,
        "orderByFields": "St_Name ASC, Add_Number ASC",
    }

    response = requests.get(ADDRESS_URL, params=params, timeout=60)
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    rows = []

    for feature in data.get("features", []):
        attrs = feature.get("attributes", {})
        geometry = feature.get("geometry", {})

        full_address = attrs.get("FullAddress")
        if not full_address:
            continue

        owner_name = fetch_owner_name_from_point(geometry.get("x"), geometry.get("y"))

        rows.append(
            {
                "full_address": full_address,
                "owner_name": owner_name,
            }
        )

    return rows


def fetch_addresses(streets, zip_codes):
    all_rows = []

    for street in streets:
        if zip_codes:
            for zip_code in zip_codes:
                all_rows.extend(fetch_addresses_for_street_zip(street, zip_code))
        else:
            all_rows.extend(fetch_addresses_for_street_zip(street))

    seen = set()
    deduped = []

    for row in all_rows:
        key = row["full_address"].upper()
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    return sorted(deduped, key=lambda r: natural_sort_key(r["full_address"]))


def csv_response(rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["full_address", "owner_name"])
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=doors_addresses.csv"},
    )


def xlsx_response(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Addresses"
    sheet.append(["full_address", "owner_name"])

    for row in rows:
        sheet.append([row["full_address"], row["owner_name"]])

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=doors_addresses.xlsx"},
    )


@app.route("/", methods=["GET", "POST"])
def index():
    rows = []
    searched = False
    streets_raw = ""
    zip_codes_raw = ""

    if request.method == "POST":
        searched = True
        streets_raw = request.form.get("streets", "").strip()
        zip_codes_raw = request.form.get("zip_codes", "").strip()

        streets = parse_list(streets_raw)
        zip_codes = parse_list(zip_codes_raw)

        if streets:
            rows = fetch_addresses(streets, zip_codes)

    return render_template_string(
        HTML,
        rows=rows,
        searched=searched,
        streets_raw=streets_raw,
        zip_codes_raw=zip_codes_raw,
    )


@app.route("/download", methods=["POST"])
def download():
    streets = parse_list(request.form.get("streets", ""))
    zip_codes = parse_list(request.form.get("zip_codes", ""))
    output_format = request.form.get("format", "csv")

    rows = fetch_addresses(streets, zip_codes)

    if output_format == "xlsx":
        return xlsx_response(rows)

    return csv_response(rows)


if __name__ == "__main__":
    app.run(debug=True)
