#!/usr/bin/env python3
"""
Step 1: Download No Power service requests.

This script:
1. Connects to the City of Cape Town ArcGIS API.
2. Checks the available fields and API record limit.
3. Retrieves the IDs of all No Power service requests.
4. Downloads the matching records in batches of 1,000.
5. Checks that the downloaded IDs and totals are correct.
6. Saves the raw dataset and extraction summary.

The script includes logging, retries and error handling.
"""

import csv
import json
import logging
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_DIR = Path(__file__).resolve().parents[1]

API_URL = (
    "https://services6.arcgis.com/nyYfO9SxHU2ChQd9/"
    "arcgis/rest/services/"
    "Service_Requests_2023_until_20_May_2026/"
    "FeatureServer/0"
)

QUERY_URL = f"{API_URL}/query"
COMPLAINT_FILTER = "C3_Complaint_Type = 'No Power'"
BATCH_SIZE = 1000

RAW_FILE = PROJECT_DIR / "data/raw/no_power_raw.csv"
SUMMARY_FILE = PROJECT_DIR / "outputs/extraction_summary.json"
SCHEMA_FILE = PROJECT_DIR / "outputs/table_schema.json"
LOG_FILE = PROJECT_DIR / "logs/extraction.log"


def setup_logging():
    """Display progress in the terminal and save it to a log file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_FILE),
        ],
    )


def create_session():
    """Create an API connection that retries temporary failures."""
    retry_settings = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )

    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry_settings)
    session.mount("https://", adapter)

    return session


def request_api(session, url, parameters, method="GET"):
    """Send an API request and return its JSON response."""
    if method == "POST":
        response = session.post(
            url, data=parameters, timeout=120
        )
    else:
        response = session.get(
            url, params=parameters, timeout=120
        )

    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict) or "error" in data:
        raise ValueError(f"Unexpected ArcGIS response: {data}")

    return data


def get_schema(session):
    """Check the required fields and obtain the CSV column names."""
    metadata = request_api(session, API_URL, {"f": "json"})

    fields = [field["name"] for field in metadata["fields"]]

    required = {"ObjectId", "Suburb", "C3_Complaint_Type"}

    if not required.issubset(fields):
        raise ValueError("Required fields are missing from the API")

    if metadata.get("objectIdField") != "ObjectId":
        raise ValueError("Unexpected ObjectId field")

    if BATCH_SIZE > metadata["maxRecordCount"]:
        raise ValueError("Batch size exceeds the API record limit")

    SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_FILE.write_text(json.dumps(metadata, indent=2))

    logging.info("Schema validated: %d fields", len(fields))
    return fields


def get_record_count(session):
    """Ask the API how many 'No Power' records exist."""
    data = request_api(
        session,
        QUERY_URL,
        {
            "f": "json",
            "where": COMPLAINT_FILTER,
            "returnCountOnly": "true",
        },
    )

    return int(data["count"])


def get_record_ids(session):
    """Retrieve and validate all matching ObjectIds."""
    data = request_api(
        session,
        QUERY_URL,
        {
            "f": "json",
            "where": COMPLAINT_FILTER,
            "returnIdsOnly": "true",
        },
    )

    if data.get("objectIdFieldName") != "ObjectId":
        raise ValueError("Unexpected ObjectId field in ID response")

    record_ids = data["objectIds"]

    if len(record_ids) != len(set(record_ids)):
        raise ValueError("Duplicate ObjectIds returned by the API")

    logging.info("Retrieved %d unique ObjectIds", len(record_ids))
    return sorted(record_ids)


def download_records(session, record_ids, columns):
    """Download all records sequentially in batches of 1,000."""
    RAW_FILE.parent.mkdir(parents=True, exist_ok=True)

    temporary_file = RAW_FILE.with_suffix(".csv.part")
    downloaded = 0
    total_batches = (len(record_ids) + BATCH_SIZE - 1) // BATCH_SIZE

    with temporary_file.open(
        "w", newline="", encoding="utf-8"
    ) as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()

        for start in range(0, len(record_ids), BATCH_SIZE):
            batch_ids = record_ids[start:start + BATCH_SIZE]

            response = request_api(
                session,
                QUERY_URL,
                {
                    "f": "json",
                    "objectIds": ",".join(map(str, batch_ids)),
                    "outFields": "*",
                    "returnGeometry": "false",
                },
                method="POST",
            )

            if response.get("exceededTransferLimit"):
                raise ValueError("API transfer limit exceeded")

            records = [
                feature["attributes"]
                for feature in response["features"]
            ]

            returned_ids = [row["ObjectId"] for row in records]

            if (
                len(returned_ids) != len(set(returned_ids))
                or set(returned_ids) != set(batch_ids)
            ):
                raise ValueError("Missing or unexpected IDs in batch")

            if any(
                row["C3_Complaint_Type"] != "No Power"
                for row in records
            ):
                raise ValueError("Unexpected complaint type in batch")

            writer.writerows(records)
            downloaded += len(records)

            batch_number = start // BATCH_SIZE + 1
            logging.info(
                "Batch %d/%d | Downloaded: %d",
                batch_number, total_batches, downloaded
            )

    if downloaded != len(record_ids):
        raise ValueError("Downloaded record count does not match IDs")

    # Replace the raw file only after successful extraction.
    temporary_file.replace(RAW_FILE)
    return downloaded


def main():
    """Run the complete data extraction and verify the final count."""
    setup_logging()
    logging.info("Starting ArcGIS data extraction")

    with create_session() as session:
        try:
            columns = get_schema(session)

            api_count = get_record_count(session)
            record_ids = get_record_ids(session)

            if len(record_ids) != api_count:
                raise ValueError("API count and ObjectIds do not match")

            downloaded = download_records(
                session, record_ids, columns
            )

            final_api_count = get_record_count(session)

            if not (api_count == downloaded == final_api_count):
                raise ValueError("Final API count reconciliation failed")

            summary = {
                "filter": COMPLAINT_FILTER,
                "api_count_before": api_count,
                "unique_object_ids": len(record_ids),
                "extracted_records": downloaded,
                "api_count_after": final_api_count,
                "batch_size": BATCH_SIZE,
                "batches": (
                    len(record_ids) + BATCH_SIZE - 1
                ) // BATCH_SIZE,
            }

            SUMMARY_FILE.write_text(
                json.dumps(summary, indent=2)
            )

            logging.info("Extraction validation PASSED")
            logging.info("Total records: %d", downloaded)

        except Exception:
            logging.exception("Extraction failed")
            raise


if __name__ == "__main__":
    main()
