"""Refresh bundled London LSOA population, median age and income references.

Run from app-crawlers: python -m sportscanner.insights.refresh_demographics

Sources (all ONS and Open Government Licence v3.0):
- Population and age bands: Nomis NM_2014_1, mid-2024, plus ONS December 2021
  population-weighted LSOA centroids V4.
- Median age: ONS ad hoc release 2093, estimates of median age for LSOAs,
  mid-2022.
- Income: ONS small area income estimates, financial year ending 2023, modelled
  mean disposable household income (equivalised, before housing costs) at MSOA
  level. ONS does not publish a small-area median, so the bundled reference
  carries the mean and the API leaves median_income null.
- LSOA to MSOA mapping: ONS OA21 to LSOA21 to MSOA21 exact-fit lookup.

The output files are small references, not request-time dependencies. The
income xlsx is read with the standard library so refreshing does not add a
spreadsheet package to the runtime.
"""

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

POPULATION_URL = "https://www.nomisweb.co.uk/api/v01/dataset/NM_2014_1/data.csv"
CENTROID_URL = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/LSOA_PopCentroids_EW_2021_V4/FeatureServer/0/query"
MEDIAN_AGE_URL = "https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/populationandmigration/populationestimates/adhocs/2093estimatesofmedianageforlowerlayersuperoutputareasinenglandandwalesmid2021andmid2022/lsoamedian2021and2022.xlsx"
INCOME_URL = "https://www.ons.gov.uk/file?uri=/employmentandlabourmarket/peopleinwork/earningsandworkinghours/datasets/smallareaincomeestimatesformiddlelayersuperoutputareasenglandandwales/financialyearending2023/datasetfinal.xlsx"
LOOKUP_URL = "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/b9ca90c10aaa4b8d9791e9859a38ca67/csv?layers=0"
LICENCE = "Open Government Licence v3.0"
DATA_DIR = Path(__file__).resolve().parent / "data"
POPULATION_TARGET = DATA_DIR / "london_lsoa_population.json"
DEMOGRAPHICS_TARGET = DATA_DIR / "london_lsoa_demographics.json"
AGE_GROUPS = {200: "population", 201: "age_0_15", 250: "age_16_24", 207: "age_25_49", 208: "age_50_64", 209: "age_65_plus"}

_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _column_index(cell_ref):
    letters = re.match(r"[A-Z]+", cell_ref or "")
    if letters is None:
        return None
    index = 0
    for letter in letters.group(0):
        index = index * 26 + ord(letter) - 64
    return index - 1


def _xlsx_rows(data, sheet_name):
    """Read one worksheet as rows of strings, using only the standard library."""
    with zipfile.ZipFile(io.BytesIO(data)) as workbook:
        shared = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(f"{_XLSX_NS}t")) for si in root.findall(f"{_XLSX_NS}si")]

        book = ET.fromstring(workbook.read("xl/workbook.xml"))
        rels = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target") for rel in rels}
        target = None
        for sheet in book.iter(f"{_XLSX_NS}sheet"):
            if sheet.get("name") == sheet_name:
                target = targets.get(sheet.get(f"{_REL_NS}id"))
                break
        if target is None:
            raise KeyError(f"Worksheet not found: {sheet_name!r}")
        path = target.lstrip("/") if target.startswith("/") else target if target.startswith("xl/") else f"xl/{target}"
        root = ET.fromstring(workbook.read(path))

        rows = []
        for row in root.iter(f"{_XLSX_NS}row"):
            cells = {}
            for cell in row.findall(f"{_XLSX_NS}c"):
                index = _column_index(cell.get("r"))
                if index is None:
                    continue
                kind = cell.get("t")
                value = cell.find(f"{_XLSX_NS}v")
                if kind == "s" and value is not None:
                    cells[index] = shared[int(value.text)]
                elif kind == "inlineStr":
                    inline = cell.find(f"{_XLSX_NS}is")
                    cells[index] = "".join(t.text or "" for t in inline.iter(f"{_XLSX_NS}t")) if inline is not None else None
                else:
                    cells[index] = value.text if value is not None else None
            if cells:
                rows.append([cells.get(i) for i in range(max(cells) + 1)])
        return rows


def _column(rows, required, prefix=None):
    header_index = next(i for i, row in enumerate(rows) if required in row)
    header = rows[header_index]
    names = [str(name).strip() if name is not None else "" for name in header]
    index = names.index(required)
    if prefix:
        index = next(i for i, name in enumerate(names) if name.startswith(prefix))
    return rows[header_index + 1:], names, index


def _load_median_age(client):
    response = client.get(MEDIAN_AGE_URL)
    response.raise_for_status()
    rows = _xlsx_rows(response.content, "Mid-2021 & 2022 LSOA")
    body, names, code_index = _column(rows, "LSOA21CD")
    age_index = next(i for i, name in enumerate(names) if name.startswith("median aged 2022"))
    return {
        str(row[code_index]).strip(): round(float(row[age_index]), 2)
        for row in body
        if len(row) > max(code_index, age_index) and row[code_index] and row[age_index]
    }


def _load_income(client):
    response = client.get(INCOME_URL)
    response.raise_for_status()
    rows = _xlsx_rows(response.content, "Net income before housing costs")
    body, names, code_index = _column(rows, "MSOA code")
    income_index = next(
        i for i, name in enumerate(names)
        if name.startswith("Disposable (net) annual income before housing costs")
    )
    return {
        str(row[code_index]).strip(): round(float(row[income_index]))
        for row in body
        if len(row) > max(code_index, income_index) and row[code_index] and row[income_index]
    }


def _load_lsoa_msoa(client):
    response = client.get(LOOKUP_URL)
    response.raise_for_status()
    mapping = {}
    for row in csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))):
        mapping.setdefault(row["LSOA21CD"], row["MSOA21CD"])
    return mapping


def main():
    people = {}
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        # Sequential requests respect Nomis concurrency guidance and keep every
        # query below the anonymous cell limit.
        for age, label in AGE_GROUPS.items():
            response = client.get(POPULATION_URL, params={
                "geography": "2013265927TYPE151", "date": "2024", "gender": 0,
                "c_age": age, "measures": 20100,
                "select": "geography_code,geography_name,obs_value,date_name",
            })
            response.raise_for_status()
            for row in csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))):
                entry = people.setdefault(row["GEOGRAPHY_CODE"], {"name": row["GEOGRAPHY_NAME"]})
                entry[label] = int(float(row["OBS_VALUE"]))
        offset = 0
        while True:
            response = client.get(CENTROID_URL, params={
                "where": "1=1", "geometry": "-0.65,51.25,0.35,51.75",
                "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
                "outFields": "LSOA21CD", "f": "json", "resultOffset": offset,
                "resultRecordCount": 2000, "orderByFields": "FID",
            })
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            features = data["features"]
            for feature in features:
                code = feature["attributes"]["LSOA21CD"]
                if code in people:
                    people[code].update(latitude=round(feature["geometry"]["y"], 6), longitude=round(feature["geometry"]["x"], 6))
            if not data.get("exceededTransferLimit"):
                break
            offset += len(features)

        median_age = _load_median_age(client)
        incomes = _load_income(client)
        lookup = _load_lsoa_msoa(client)

    missing = [code for code, row in people.items() if "latitude" not in row or any(g not in row for g in AGE_GROUPS.values())]
    if missing:
        raise RuntimeError(f"Incomplete population reference: {len(missing)} missing centroids or age counts")
    missing_demographics = [
        code for code in people
        if code not in median_age or lookup.get(code) not in incomes
    ]
    if missing_demographics:
        raise RuntimeError(f"Incomplete demographics reference: {len(missing_demographics)} missing median ages or incomes")

    population = {
        "year": 2024, "geography": "London LSOAs (2021 boundaries)",
        "source": "ONS mid-2024 small area population estimates via Nomis NM_2014_1; ONS December 2021 population-weighted LSOA centroids V4",
        "source_urls": [POPULATION_URL, CENTROID_URL],
        "licence": "Contains National Statistics data and OS data, Crown copyright and database right. Open Government Licence v3.0.",
        "areas": [{"code": code, **row} for code, row in sorted(people.items())],
    }
    demographics = {
        "median_age": {
            "year": 2022,
            "source": "ONS estimates of median age for Lower layer Super Output Areas in England and Wales, mid-2022 (ad hoc release 2093, 23 May 2024)",
            "source_url": MEDIAN_AGE_URL,
            "licence": LICENCE,
        },
        "income": {
            "year": "2023",
            "period": "Financial year ending March 2023",
            "measure": "mean",
            "definition": "Mean disposable (net) annual household income, equivalised, before housing costs",
            "source": "ONS income estimates for small areas, England and Wales, financial year ending 2023 (MSOAs, released 10 December 2025)",
            "source_url": INCOME_URL,
            "lookup_url": LOOKUP_URL,
            "licence": LICENCE,
        },
        "areas": [
            {
                "code": code,
                "msoa_code": lookup[code],
                "median_age": median_age[code],
                "mean_income": incomes[lookup[code]],
            }
            for code in sorted(people)
        ],
    }
    POPULATION_TARGET.write_text(json.dumps(population, separators=(",", ":")) + "\n")
    DEMOGRAPHICS_TARGET.write_text(json.dumps(demographics, separators=(",", ":")) + "\n")
    print(f"Wrote {len(people)} London LSOAs, population {sum(r['population'] for r in people.values()):,}")
    print(f"Wrote median age and mean income for {len(demographics['areas'])} LSOAs")


if __name__ == "__main__":
    main()
