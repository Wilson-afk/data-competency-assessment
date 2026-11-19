#!/usr/bin/env python3
"""
Download No Power service requests from the City of Cape Town.

The records are retrieved from ArcGIS in batches. The script
checks the downloaded IDs and saves the raw data for analysis.
"""

import csv
import json
import logging
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Settings

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


# Helpers

def format_time(seconds):
    """Convert seconds into a readable time."""
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def show_progress(completed, total, elapsed):
    """Update the download progress on one terminal line."""
    import sys

    progress = completed / total if total else 1
    filled = int(25 * progress)
    bar = "#" * filled + "-" * (25 - filled)

    remaining = (
        elapsed * (total - completed) / completed
        if completed else 0
    )

    message = (
        f"Downloading: [{bar}] {progress:.0%} "
        f"| {completed:,}/{total:,} records "
        f"| Elapsed: {format_time(elapsed)} "
        f"| Remaining: ~{format_time(remaining)}"
    )

    if sys.stdout.isatty():
        # Redraw the same line instead of printing new lines.
        sys.stdout.write("\r" + message.ljust(115))
        sys.stdout.flush()
    elif completed == total:
        # In captured output, show only the final result.
        print(message, flush=True)


def setup_logging():
    """Display messages and save them to a log file."""
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
    """Create an API connection with automatic retries."""
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )

    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retries)

    session.mount("https://", adapter)

    return session


def request_api(session, url, parameters, method="GET"):
    """Send a request and return the API response."""
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
        raise ValueError(f"ArcGIS API error: {data}")

    return data


# API information

def get_schema(session, batch_size):
    """Check the available fields and maximum batch size."""
    metadata = request_api(session, API_URL, {"f": "json"})

    columns = [field["name"] for field in metadata["fields"]]

    required = {"ObjectId", "Suburb", "C3_Complaint_Type"}

    if not required.issubset(columns):
        raise ValueError("Required API fields are missing")

    if metadata.get("objectIdField") != "ObjectId":
        raise ValueError("Unexpected ObjectId field")

    maximum = int(metadata["maxRecordCount"])

    if batch_size > maximum:
        raise ValueError(
            f"Requested batch size {batch_size} exceeds "
            f"the API limit of {maximum}"
        )

    SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_FILE.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    logging.info("The API contains %d fields.", len(columns))
    logging.info("Maximum records per API request: %d", maximum)
    logging.info("Downloading up to %d records per batch.", batch_size)

    return columns


def get_record_count(session):
    """Count the matching No Power records."""
    result = request_api(
        session,
        QUERY_URL,
        {
            "f": "json",
            "where": COMPLAINT_FILTER,
            "returnCountOnly": "true",
        },
    )

    return int(result["count"])



def get_total_record_count(session):
    """Count all records in the source table before filtering."""
    result = request_api(
        session,
        QUERY_URL,
        {
            "f": "json",
            "where": "1=1",
            "returnCountOnly": "true",
        },
    )

    return int(result["count"])


def get_record_ids(session):
    """Retrieve all matching ObjectIds."""
    result = request_api(
        session,
        QUERY_URL,
        {
            "f": "json",
            "where": COMPLAINT_FILTER,
            "returnIdsOnly": "true",
        },
    )

    if result.get("objectIdFieldName") != "ObjectId":
        raise ValueError("Unexpected ObjectId field in ID response")

    record_ids = result["objectIds"]

    if len(record_ids) != len(set(record_ids)):
        raise ValueError("Duplicate ObjectIds returned")

    return sorted(record_ids)


# Download records

def download_records(session, record_ids, columns, batch_size):
    """Download all records in batches and display progress."""
    RAW_FILE.parent.mkdir(parents=True, exist_ok=True)

    temporary_file = RAW_FILE.with_suffix(".csv.part")

    total = len(record_ids)
    downloaded = 0
    start_time = time.perf_counter()

    with temporary_file.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()

        for start in range(0, total, batch_size):
            batch_ids = record_ids[start:start + batch_size]

            result = request_api(
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

            if result.get("exceededTransferLimit"):
                raise ValueError("API transfer limit exceeded")

            records = [
                feature["attributes"]
                for feature in result["features"]
            ]

            returned_ids = [row["ObjectId"] for row in records]

            if (
                len(returned_ids) != len(set(returned_ids))
                or set(returned_ids) != set(batch_ids)
            ):
                raise ValueError(
                    "Missing or unexpected ObjectIds in batch"
                )

            if any(
                row["C3_Complaint_Type"] != "No Power"
                for row in records
            ):
                raise ValueError("Unexpected complaint type")

            writer.writerows(records)
            downloaded += len(records)

            elapsed = time.perf_counter() - start_time
            show_progress(downloaded, total, elapsed)

    print()  # Move to the next line after the progress bar.

    if downloaded != total:
        raise ValueError("Downloaded count does not match IDs")

    # Preserve the previous raw CSV until extraction succeeds.
    temporary_file.replace(RAW_FILE)

    return downloaded


# Main pipeline

def main():
    """Download, validate and save all matching records."""
    setup_logging()
    started = time.perf_counter()

    logging.info("Connecting to the City of Cape Town ArcGIS API...")

    try:
        with create_session() as session:
            columns = get_schema(session, BATCH_SIZE)

            source_count = get_total_record_count(session)
            api_count = get_record_count(session)
            record_ids = get_record_ids(session)

            logging.info(
                "Total records in the source table: %s",
                f"{source_count:,}",
            )
            logging.info(
                "Records classified as 'No Power': %s",
                f"{api_count:,}",
            )
            logging.info(
                "No Power share: %.2f%%",
                api_count / source_count * 100 if source_count else 0,
            )

            if len(record_ids) != api_count:
                raise ValueError("API count and ObjectIds differ")


            total_batches = (
                len(record_ids) + BATCH_SIZE - 1
            ) // BATCH_SIZE

            logging.info("The download will use %d batches.", total_batches)

            downloaded = download_records(
                session, record_ids, columns, BATCH_SIZE
            )

            final_count = get_record_count(session)

            if not (api_count == downloaded == final_count):
                raise ValueError("Final API counts do not reconcile")

            elapsed = time.perf_counter() - started

            summary = {
                "filter": COMPLAINT_FILTER,
                "source_total_records": source_count,
                "api_count_before": api_count,
                "unique_object_ids": len(record_ids),
                "extracted_records": downloaded,
                "api_count_after": final_count,
                "batch_size": BATCH_SIZE,
                "batches": total_batches,
                "extraction_seconds": round(elapsed, 2),
            }

            SUMMARY_FILE.write_text(
                json.dumps(summary, indent=2),
                encoding="utf-8",
            )

            logging.info("The downloaded records match the API totals.")
            logging.info("Successfully downloaded %d records.", downloaded)
            logging.info("Time spent downloading and checking the data: %s", format_time(elapsed))

    except Exception:
        logging.exception("Extraction failed")
        raise


if __name__ == "__main__":
    main()
