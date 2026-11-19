#!/usr/bin/env python3
"""
Step 3: Validate the extracted and processed data.

This script:
1. Loads the extracted and processed datasets.
2. Checks that required columns are present.
3. Verifies that record identifiers are unique.
4. Confirms that all records are No Power complaints.
5. Compares extracted record counts with the API count.
6. Checks that unresolved suburb records are documented.
7. Independently calculates suburb counts again.
8. Verifies that all record totals reconcile.
9. Saves a validation report and logs the results.

The pipeline stops if any validation check fails.
"""

import json
import logging
from pathlib import Path

import pandas as pd


# --------------------------------------------------
# 1. File paths
# --------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_DIR / "data"
OUTPUT_DIR = PROJECT_DIR / "outputs"
LOG_FILE = PROJECT_DIR / "logs/validation.log"


# --------------------------------------------------
# 2. Logging
# --------------------------------------------------

def setup_logging():
    """Display validation messages and save them to a log file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_FILE),
        ],
    )


# --------------------------------------------------
# 3. Validation helper
# --------------------------------------------------

def check(condition, message):
    """Stop execution if a validation check fails."""
    if not condition:
        raise ValueError(message)


# --------------------------------------------------
# 4. Load and validate data
# --------------------------------------------------

def validate_data():
    """Check records, identifiers, exclusions and suburb counts."""

    logging.info("Loading extracted and processed datasets")

    raw = pd.read_csv(
        DATA_DIR / "raw/no_power_raw.csv",
        dtype={"ObjectId": "string"},
        low_memory=False,
    )

    cleaned = pd.read_csv(
        DATA_DIR / "processed/no_power_clean.csv",
        dtype={"ObjectId": "string"},
        low_memory=False,
    )

    counts = pd.read_csv(
        OUTPUT_DIR / "no_power_by_suburb.csv"
    )

    excluded = pd.read_csv(
        OUTPUT_DIR / "excluded_suburbs.csv",
        dtype={"ObjectId": "string"},
    )

    with (OUTPUT_DIR / "extraction_summary.json").open(
        encoding="utf-8"
    ) as file:
        extraction = json.load(file)

    # --------------------------------------------------
    # Check 1: Required columns
    # --------------------------------------------------

    required_raw = {
        "ObjectId",
        "C3_Complaint_Type",
        "Suburb",
    }

    required_cleaned = {
        "ObjectId",
        "Suburb_clean",
    }

    check(
        required_raw.issubset(raw.columns),
        "Missing required columns in raw data",
    )

    check(
        required_cleaned.issubset(cleaned.columns),
        "Missing required columns in cleaned data",
    )

    check(
        set(counts.columns) == {"suburb", "report_count"},
        "Incorrect columns in final aggregation",
    )

    check(
        {"ObjectId", "exclusion_reason"}.issubset(excluded.columns),
        "Missing required columns in exclusion report",
    )

    logging.info("PASSED: Required columns")

    # --------------------------------------------------
    # Check 2: Unique identifiers
    # --------------------------------------------------

    check(
        raw["ObjectId"].notna().all(),
        "Missing ObjectIds in raw data",
    )

    check(
        raw["ObjectId"].is_unique,
        "Duplicate ObjectIds in raw data",
    )

    check(
        cleaned["ObjectId"].notna().all(),
        "Missing ObjectIds in cleaned data",
    )

    check(
        cleaned["ObjectId"].is_unique,
        "Duplicate ObjectIds in cleaned data",
    )

    logging.info("PASSED: ObjectId validation")

    # --------------------------------------------------
    # Check 3: Complaint type
    # --------------------------------------------------

    check(
        raw["C3_Complaint_Type"].eq("No Power").all(),
        "Raw data contains unexpected complaint types",
    )

    logging.info("PASSED: Complaint type validation")

    # --------------------------------------------------
    # Check 4: API and extracted record counts
    # --------------------------------------------------

    expected = extraction["api_count_before"]

    check(
        len(raw)
        == len(cleaned)
        == expected
        == extraction["unique_object_ids"]
        == extraction["extracted_records"]
        == extraction["api_count_after"],
        "API, raw and cleaned record counts do not reconcile",
    )

    check(
        set(raw["ObjectId"]) == set(cleaned["ObjectId"]),
        "Raw and cleaned ObjectIds do not match",
    )

    logging.info("PASSED: API and extracted count reconciliation")

    # --------------------------------------------------
    # Check 5: Excluded records
    # --------------------------------------------------

    unresolved = cleaned[
        cleaned["Suburb_clean"].isna()
    ]

    check(
        excluded["ObjectId"].notna().all(),
        "Missing ObjectIds in exclusion report",
    )

    check(
        excluded["ObjectId"].is_unique,
        "Duplicate ObjectIds in exclusion report",
    )

    check(
        set(unresolved["ObjectId"]) == set(excluded["ObjectId"]),
        "Excluded records do not match unresolved suburbs",
    )

    logging.info("PASSED: Excluded records validation")

    # --------------------------------------------------
    # Check 6: Independently calculate suburb counts
    # --------------------------------------------------

    independent_counts = (
        cleaned
        .dropna(subset=["Suburb_clean"])
        .groupby("Suburb_clean")
        .size()
        .reset_index(name="report_count")
        .rename(columns={"Suburb_clean": "suburb"})
        .sort_values(
            ["report_count", "suburb"],
            ascending=[False, True],
        )
        .reset_index(drop=True)
    )

    pd.testing.assert_frame_equal(
        counts.reset_index(drop=True),
        independent_counts,
        check_dtype=False,
    )

    logging.info("PASSED: Independent suburb aggregation")

    # --------------------------------------------------
    # Check 7: Final record reconciliation
    # --------------------------------------------------

    included = int(counts["report_count"].sum())
    omitted = len(excluded)

    check(
        included + omitted == len(raw),
        "Aggregated and excluded records do not reconcile",
    )

    check(
        counts["suburb"].notna().all(),
        "Final aggregation contains missing suburb values",
    )

    check(
        counts["suburb"].is_unique,
        "Final aggregation contains duplicate suburb labels",
    )

    check(
        counts["report_count"].notna().all()
        and (counts["report_count"] >= 0).all()
        and (counts["report_count"] % 1 == 0).all(),
        "Report counts must be non-negative integers",
    )

    check(
        counts["report_count"].is_monotonic_decreasing,
        "Suburb counts are not sorted in descending order",
    )

    logging.info(
        "PASSED: Final reconciliation (%d + %d = %d)",
        included,
        omitted,
        len(raw),
    )

    # --------------------------------------------------
    # Return validation summary
    # --------------------------------------------------

    return {
        "status": "PASSED",
        "api_records": expected,
        "raw_records": len(raw),
        "aggregated_records": included,
        "excluded_records": omitted,
        "distinct_suburb_labels": len(counts),
    }


# --------------------------------------------------
# 5. Run validation
# --------------------------------------------------

def main():
    """Execute all validation checks and save the report."""

    setup_logging()

    try:
        report = validate_data()

        report_file = OUTPUT_DIR / "validation_report.json"

        report_file.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        logging.info("ALL VALIDATION CHECKS PASSED")
        logging.info("Summary: %s", report)

    except Exception:
        logging.exception("Validation failed")
        raise


if __name__ == "__main__":
    main()
