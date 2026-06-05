import csv
import io
import re

import requests
from flask import Flask, Response, render_template_string, request

app = Flask(__name__)

URL = "https://gcgis.guilfordcountync.gov/arcgis/rest/services/SiteStructureAddressPoints/FeatureServer/0/query"

HTML = """
<!doctype html>
<html>
<head>
    <title>Doors | Adalia Works</title>
    <link rel="icon" href="data:,">

    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 700px;
            margin: 50px auto;
            padding: 20px;
            min-height: 80vh;
        }

        h1 {
            margin-bottom: 5px;
        }

        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }

        input, button {
            width: 100%;
            padding: 10px;
            margin-top: 8px;
            margin-bottom: 20px;
            font-size: 16px;
            box-sizing: border-box;
        }

        button {
            cursor: pointer;
        }

        footer {
            margin-top: 60px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #666;
            font-size: 14px;
        }

        footer a {
            color: #666;
            text-decoration: none;
        }

        footer a:hover {
            text-decoration: underline;
        }

        footer small {
            display: block;
            margin-top: 6px;
            color: #888;
        }
    </style>
</head>

<body>

    <h1>Doors</h1>

    <div class="subtitle">
        Powered by Guilford County GIS
    </div>

    <form method="post" action="/download">

        <label>Street Name(s)</label>

        <input
            type="text"
            name="streets"
            placeholder="Woodland Drive, Elm Street"
            required
        >

        <label>ZIP Code</label>

        <input
            type="text"
            name="zip_code"
            placeholder="27408"
            required
        >

        <button type="submit">
            Download CSV
        </button>

    </form>

    <footer>
        &copy; Adalia Works |
        <a href="https://adaliaworks.com" target="_blank" rel="noopener noreferrer">
            adaliaworks.com
        </a>
        <small>Doors v0.3</small>
    </footer>

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


def fetch_addresses_for_street(street, zip_code):
    street_name, street_type = split_street(street)

    if street_type:
        street_type = normalize_type(street_type)

    where = (
        f"UPPER(St_Name) = '{sql_escape(street_name.upper())}' "
        f"AND Post_Code = '{sql_escape(zip_code)}'"
    )

    if street_type:
        where += f" AND St_PosTyp = '{sql_escape(street_type)}'"

    params = {
        "where": where,
        "outFields": "Add_Number,St_Name,St_PosTyp,Post_Code,FullAddress",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": 2000,
        "orderByFields": "St_Name ASC, Add_Number ASC",
    }

    response = requests.get(URL, params=params, timeout=60)
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    rows = []

    for feature in data.get("features", []):
        attrs = feature.get("attributes", {})
        full_address = attrs.get("FullAddress")

        if full_address:
            rows.append({"full_address": full_address})

    return rows


def fetch_addresses(streets, zip_code):
    all_rows = []

    for street in streets:
        all_rows.extend(fetch_addresses_for_street(street, zip_code))

    seen = set()
    deduped = []

    for row in all_rows:
        key = row["full_address"].upper()

        if key not in seen:
            seen.add(key)
            deduped.append(row)

    return sorted(deduped, key=lambda r: natural_sort_key(r["full_address"]))


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/download", methods=["POST"])
def download():
    streets_raw = request.form.get("streets", "")
    zip_code = request.form.get("zip_code", "").strip()

    streets = [s.strip() for s in streets_raw.split(",") if s.strip()]

    rows = fetch_addresses(streets, zip_code)

    output = io.StringIO()

    writer = csv.DictWriter(output, fieldnames=["full_address"])

    writer.writeheader()

    for row in rows:
        writer.writerow({"full_address": row["full_address"]})

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=doors_{zip_code}.csv"},
    )


if __name__ == "__main__":
    app.run(debug=True)
