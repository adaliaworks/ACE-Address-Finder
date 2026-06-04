#!/usr/bin/env python3

import csv
import re
import requests
from pathlib import Path

URL = "https://gcgis.guilfordcountync.gov/arcgis/rest/services/SiteStructureAddressPoints/FeatureServer/0/query"


def safe_filename(text):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_")


def natural_sort_key(value):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(value))]


def split_street(street):
    parts = street.strip().split()

    street_types = {
        "street", "st", "drive", "dr", "road", "rd", "avenue", "ave",
        "lane", "ln", "court", "ct", "circle", "cir", "place", "pl",
        "boulevard", "blvd", "way", "trail", "trl", "parkway", "pkwy",
        "terrace", "ter", "loop", "pass", "alley", "aly"
    }

    if len(parts) > 1 and parts[-1].lower() in street_types:
        return " ".join(parts[:-1]), parts[-1]

    return street.strip(), ""


def normalize_type(st_type):
    mapping = {
        "dr": "Drive", "drive": "Drive",
        "st": "Street", "street": "Street",
        "rd": "Road", "road": "Road",
        "ave": "Avenue", "avenue": "Avenue",
        "ln": "Lane", "lane": "Lane",
        "ct": "Court", "court": "Court",
        "cir": "Circle", "circle": "Circle",
        "pl": "Place", "place": "Place",
        "blvd": "Boulevard", "boulevard": "Boulevard",
        "way": "Way",
        "trl": "Trail", "trail": "Trail",
        "pkwy": "Parkway", "parkway": "Parkway",
        "ter": "Terrace", "terrace": "Terrace",
        "loop": "Loop",
        "pass": "Pass",
        "aly": "Alley", "alley": "Alley",
    }

    return mapping.get(st_type.lower(), st_type.title())


def sql_escape(value):
    return value.replace("'", "''")


def fetch_addresses_for_street(street, zip_code):
    street_name, street_type = split_street(street)
    street_type = normalize_type(street_type) if street_type else ""

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

    r = requests.get(URL, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    rows = []

    for feature in data.get("features", []):
        attrs = feature.get("attributes", {})

        number = attrs.get("Add_Number", "")
        name = attrs.get("St_Name", "")
        street_type = attrs.get("St_PosTyp", "")
        full_street = f"{name} {street_type}".strip()

        full_address = attrs.get("FullAddress") or f"{number} {full_street}".strip()

        rows.append({
            "street_number": number,
            "street_name": full_street,
            "full_address": full_address,
        })

    return rows


def fetch_addresses(streets, zip_code):
    all_rows = []

    for street in streets:
        print(f"Querying {street}...")
        rows = fetch_addresses_for_street(street, zip_code)
        print(f"  Found {len(rows)} addresses.")
        all_rows.extend(rows)

    seen = set()
    deduped = []

    for row in all_rows:
        key = row["full_address"].upper()
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    return sorted(
        deduped,
        key=lambda r: (r["street_name"].lower(), natural_sort_key(r["street_number"]))
    )


def write_csv(rows, streets, zip_code):
    street_part = safe_filename("_".join(streets))
    path = Path(f"guilford_addresses_{street_part}_{zip_code}.csv")

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["full_address"])
        writer.writeheader()

        for row in rows:
            writer.writerow({"full_address": row["full_address"]})

    return path


def main():
    street_input = input(
        "Street name(s), comma-separated, e.g. Woodland Drive, Elm Street: "
    ).strip()

    zip_code = input("ZIP code, e.g. 27408: ").strip()

    streets = [s.strip() for s in street_input.split(",") if s.strip()]

    if not streets or not zip_code:
        raise SystemExit("At least one street name and ZIP code are required.")

    rows = fetch_addresses(streets, zip_code)

    if not rows:
        print("No matching addresses found.")
        return

    output = write_csv(rows, streets, zip_code)

    print(f"Found {len(rows)} total unique addresses.")
    print(f"Wrote CSV: {output}")


if __name__ == "__main__":
    main()
