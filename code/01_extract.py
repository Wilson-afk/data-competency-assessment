#!/usr/bin/env python3
"""Extract all 'No Power' records from the Cape Town C3 ArcGIS API."""

import csv
import json
import logging
import sys
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = (
    "https://services6.arcgis.com/"
    "nyYfO9SxHU2ChQd9/arcgis/rest/services/"
    "Service_Requests_2023_until_20_May_2026/FeatureServer/0"
)
QUERY_URL = BASE_URL + "/query"

WHERE = "C3_Complaint_Type = 'No Power'"
BATCH_SIZE = 1000

RAW_FILE = ROOT / "data/raw/no_power_raw.csv"
SCHEMA_FILE = ROOT / "outputs/table_schema.json"
SUMMARY_FILE = ROOT / "outputs/extraction_summary.json"
LOG_FILE = ROOT / "logs/extraction.log"

LOGGER = logging.getLogger("cider.extract")


def setup_logging():
    """Configure console and file logging."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, mode="a"),
        ],
    )


def create_session():
    """Create a session with retries and exponential back-off."""
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        respect_retry_after_header=True,
    )

    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)

    return session


def request_json(session, url, params, method="GET"):
    """Request JSON and reject HTTP or ArcGIS service errors."""
    if method == "POST":
        response = session.post(
            url, data=params, timeout=120
        )
    else:
        response = session.get(
            url, params=params, timeout=120
        )

    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Unexpected API response structure")

    if "error" in data:
        raise RuntimeError(f"ArcGIS error: {data['error']}")

    return data


def inspect_schema(session):
    """Verify table metadata and required fields."""
    metadata = request_json(
        session, BASE_URL, {"f": "json"}
    )

    fields = metadata.get("fields", [])
    names = [field["name"] for field in fields]

    required = {
        "ObjectId", "Suburb", "C3_Complaint_Type"
    }
    missing = required - set(names)

    if missing:
        raise ValueError(
            f"Required fields missing: {sorted(missing)}"
        )

    if metadata.get("objectIdField") != "ObjectId":
        raise ValueError("Unexpected ObjectId field")

    max_records = metadata.get("maxRecordCount")
    if not isinstance(max_records, int) or max_records < 1:
        raise ValueError("Invalid API maximum record count")

    if BATCH_SIZE > max_records:
        raise ValueError(
            f"Batch size {BATCH_SIZE} exceeds {max_records}"
        )

    SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_FILE.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    LOGGER.info("Schema validated: %d fields", len(fields))
    LOGGER.info("Maximum records per query: %d", max_records)

    return names


def get_count(session):
    """Retrieve the API count for the exact complaint filter."""
    result = request_json(
        session,
        QUERY_URL,
        {
            "f": "json",
            "where": WHERE,
            "returnCountOnly": "true",
        },
    )

    if "count" not in result:
        raise ValueError("API count missing")

    return int(result["count"])


def get_object_ids(session):
    """Retrieve matching ObjectIds and validate uniqueness."""
    result = request_json(
        session,
        QUERY_URL,
        {
            "f": "json",
            "where": WHERE,
            "returnIdsOnly": "true",
        },
    )

    if result.get("objectIdFieldName") != "ObjectId":
        raise ValueError("Unexpected ObjectId field in response")

    ids = result.get("objectIds")
    if not isinstance(ids, list):
        raise ValueError("ObjectIds missing from API response")

    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate ObjectIds returned")

    ids.sort()
    LOGGER.info("Retrieved %d unique ObjectIds", len(ids))

    return ids


def fetch_batch(session, ids):
    """Retrieve one batch and verify its IDs and complaint values."""
    result = request_json(
        session,
        QUERY_URL,
        {
            "f": "json",
            "objectIds": ",".join(map(str, ids)),
            "outFields": "*",
            "returnGeometry": "false",
        },
        method="POST",
    )

    features = result.get("features")

    if not isinstance(features, list):
        raise ValueError("API features missing")

    if result.get("exceededTransferLimit"):
        raise ValueError("API transfer limit exceeded")

    records = []

    for feature in features:
        attributes = feature.get("attributes")
        if not isinstance(attributes, dict):
            raise ValueError("Invalid feature attributes")
        records.append(attributes)

    received_ids = [row.get("ObjectId") for row in records]

    if (
        len(received_ids) != len(set(received_ids))
        or set(received_ids) != set(ids)
        or len(records) != len(ids)
    ):
        raise ValueError("Batch ObjectIds do not reconcile")

    if any(
        row.get("C3_Complaint_Type") != "No Power"
        for row in records
    ):
        raise ValueError("Unexpected complaint type in batch")

    return records


def extract(session, ids, fieldnames):
    """Download all ID batches and save raw records atomically."""
    RAW_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = RAW_FILE.with_suffix(".csv.part")

    total = 0
    batches = (len(ids) + BATCH_SIZE - 1) // BATCH_SIZE

    with temp_file.open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()

        for index, start in enumerate(
            range(0, len(ids), BATCH_SIZE), start=1
        ):
            batch_ids = ids[start:start + BATCH_SIZE]
            records = fetch_batch(session, batch_ids)

            writer.writerows(records)
            total += len(records)

            LOGGER.info(
                "Batch %d/%d | records=%d | total=%d",
                index, batches, len(records), total,
            )

    if total != len(ids):
        temp_file.unlink(missing_ok=True)
        raise ValueError("Final extraction count mismatch")

    temp_file.replace(RAW_FILE)

    return total, batches


def main():
    """Run full extraction and count reconciliation."""
    setup_logging()
    LOGGER.info("Starting PHDC No Power extraction")

    session = create_session()

    try:
        fields = inspect_schema(session)

        expected_before = get_count(session)
        ids = get_object_ids(session)

        LOGGER.info(
            "API count before extraction: %d",
            expected_before,
        )

        if len(ids) != expected_before:
            raise ValueError("ObjectIds and API count disagree")

        extracted, batches = extract(session, ids, fields)
        expected_after = get_count(session)

        summary = {
            "filter": WHERE,
            "api_count_before": expected_before,
            "unique_object_ids": len(ids),
            "extracted_records": extracted,
            "api_count_after": expected_after,
            "batch_size": BATCH_SIZE,
            "batches": batches,
        }

        if not (
            expected_before
            == len(ids)
            == extracted
            == expected_after
        ):
            raise ValueError(
                f"Count reconciliation failed: {summary}"
            )

        SUMMARY_FILE.write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )

        LOGGER.info("Extraction validation PASSED")
        LOGGER.info("Summary: %s", summary)

    except Exception:
        LOGGER.exception("Extraction failed")
        raise

    finally:
        session.close()


if __name__ == "__main__":
    main()
