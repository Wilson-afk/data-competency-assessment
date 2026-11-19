#!/usr/bin/env python3
"""
Step 2: Clean suburb names and count reports.

This script:
1. Loads the previously downloaded No Power records.
2. Checks the required columns and record identifiers.
3. Standardises suburb names by removing extra spaces
   and using consistent capitalisation.
4. Identifies missing, blank and placeholder suburb values.
5. Counts valid reports for each cleaned suburb.
6. Saves the cleaned data, suburb counts and exclusions.
7. Checks that all extracted records are accounted for.

Original suburb values are preserved for traceability.
"""

import json
import logging
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]

RAW_FILE = PROJECT_DIR / "data/raw/no_power_raw.csv"
CLEAN_FILE = PROJECT_DIR / "data/processed/no_power_clean.csv"
RESULT_FILE = PROJECT_DIR / "outputs/no_power_by_suburb.csv"
EXCLUDED_FILE = PROJECT_DIR / "outputs/excluded_suburbs.csv"
SUMMARY_FILE = PROJECT_DIR / "outputs/transformation_summary.json"
LOG_FILE = PROJECT_DIR / "logs/transformation.log"

# Values that do not identify a usable suburb.
INVALID_SUBURBS = {
    "#",
    "UNKNOWN",
    "GENERIC TOWN 0000",
    "N/A",
    "NA",
    "NULL",
    "NONE",
    "UNSPECIFIED",
}


def setup_logging():
    """Display progress in the terminal and write a log file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_FILE),
        ],
    )


def load_data():
    """Load the extracted records and validate their identifiers."""
    if not RAW_FILE.exists():
        raise FileNotFoundError(f"Missing input file: {RAW_FILE}")

    data = pd.read_csv(
        RAW_FILE,
        dtype={
            "ObjectId": "string",
            "Suburb": "string",
            "C3_Complaint_Type": "string",
        },
        low_memory=False,
    )

    required = {"ObjectId", "Suburb", "C3_Complaint_Type"}

    if not required.issubset(data.columns):
        raise ValueError("Required columns are missing")

    if data["ObjectId"].isna().any():
        raise ValueError("Missing ObjectIds")

    if data["ObjectId"].duplicated().any():
        raise ValueError("Duplicate ObjectIds")

    if not data["C3_Complaint_Type"].eq("No Power").all():
        raise ValueError("Unexpected complaint types")

    logging.info("Loaded %d records", len(data))
    return data


def clean_suburbs(data):
    """Standardise suburb labels and identify unresolved values."""
    data = data.copy()

    # Preserve the original suburb for traceability.
    data["Suburb_original"] = data["Suburb"]

    data["Suburb_clean"] = (
        data["Suburb"]
        .fillna("")
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
    )

    missing = data["Suburb_clean"].eq("")
    placeholder = data["Suburb_clean"].isin(INVALID_SUBURBS)

    data["exclusion_reason"] = pd.NA

    data.loc[missing, "exclusion_reason"] = "missing_or_blank"
    data.loc[
        placeholder & ~missing,
        "exclusion_reason",
    ] = "placeholder_or_unknown"

    # Excluded values remain traceable in Suburb_original.
    data.loc[
        data["exclusion_reason"].notna(),
        "Suburb_clean",
    ] = pd.NA

    return data


def count_reports_by_suburb(data):
    """Count valid reports per suburb, sorted highest to lowest."""
    valid_records = data.dropna(subset=["Suburb_clean"])

    counts = (
        valid_records
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

    return counts


def main():
    """Clean suburb values, aggregate reports and save the results."""
    setup_logging()

    try:
        data = load_data()
        cleaned = clean_suburbs(data)

        excluded = cleaned[
            cleaned["exclusion_reason"].notna()
        ].copy()

        counts = count_reports_by_suburb(cleaned)

        included_total = int(counts["report_count"].sum())
        excluded_total = len(excluded)

        if included_total + excluded_total != len(data):
            raise ValueError("Record totals do not reconcile")

        if not counts["report_count"].is_monotonic_decreasing:
            raise ValueError("Report counts are not sorted")

        CLEAN_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)

        cleaned.to_csv(CLEAN_FILE, index=False)
        counts.to_csv(RESULT_FILE, index=False)

        excluded[
            ["ObjectId", "Suburb_original", "exclusion_reason"]
        ].to_csv(EXCLUDED_FILE, index=False)

        summary = {
            "status": "PASSED",
            "total_records": len(data),
            "aggregated_records": included_total,
            "excluded_records": excluded_total,
            "distinct_suburbs": len(counts),
            "exclusions_by_reason": {
                str(reason): int(number)
                for reason, number in excluded[
                    "exclusion_reason"
                ].value_counts().items()
            },
        }

        SUMMARY_FILE.write_text(
            json.dumps(summary, indent=2)
        )

        logging.info(
            "Reconciliation PASSED: %d + %d = %d",
            included_total, excluded_total, len(data)
        )

        logging.info("Transformation validation PASSED")

    except Exception:
        logging.exception("Transformation failed")
        raise


if __name__ == "__main__":
    main()
