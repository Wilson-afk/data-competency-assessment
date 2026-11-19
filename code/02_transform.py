#!/usr/bin/env python3
"""
Clean suburb names and count No Power service requests.

Missing and placeholder suburb names are kept as separate
categories so that every downloaded record is counted.
"""

import json
import logging
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]

RAW_FILE = PROJECT_DIR / "data/raw/no_power_raw.csv"
CLEAN_FILE = PROJECT_DIR / "data/processed/no_power_clean.csv"
RESULT_FILE = PROJECT_DIR / "outputs/no_power_by_suburb.csv"
SUMMARY_FILE = PROJECT_DIR / "outputs/transformation_summary.json"
LOG_FILE = PROJECT_DIR / "logs/transformation.log"

UNKNOWN_LABEL = "UNKNOWN"

# Confirmed spelling and spacing corrections.
SUBURB_CORRECTIONS = {
    "PHILLIPI": "PHILIPPI",
    "GUGULETHU": "GUGULETU",
    "FISHHOEK": "FISH HOEK",
}


# These values do not identify a usable suburb.
PLACEHOLDER_VALUES = {
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
    """Show progress in the terminal and save a log file."""
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
    """Load the No Power records and check their identifiers."""
    if not RAW_FILE.exists():
        raise FileNotFoundError(f"Raw data not found: {RAW_FILE}")

    records = pd.read_csv(
        RAW_FILE,
        dtype={
            "ObjectId": "string",
            "Suburb": "string",
            "C3_Complaint_Type": "string",
        },
        low_memory=False,
    )

    required = {"ObjectId", "Suburb", "C3_Complaint_Type"}

    if not required.issubset(records.columns):
        raise ValueError("Required columns are missing")

    if records["ObjectId"].isna().any():
        raise ValueError("Some records have missing ObjectIds")

    if not records["ObjectId"].is_unique:
        raise ValueError("Duplicate ObjectIds found")

    if not records["C3_Complaint_Type"].eq("No Power").all():
        raise ValueError("Unexpected complaint types found")

    logging.info(
        "Loaded %s service-request records classified as 'No Power'.",
        f"{len(records):,}",
    )

    return records


def clean_suburbs(records):
    """Clean suburb names and identify missing or placeholder values."""
    records = records.copy()

    # Keep the original value so changes can be checked later.
    records["Suburb_original"] = records["Suburb"]

    records["Suburb_clean"] = (
        records["Suburb"]
        .fillna("")
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
        .replace(SUBURB_CORRECTIONS)
    )

    missing = records["Suburb_clean"].eq("")
    placeholder = (
        records["Suburb_clean"].isin(PLACEHOLDER_VALUES)
        | records["Suburb_clean"].str.fullmatch(
            r"\d+|[^A-Z0-9\s]+", na=False
        )
    )

    records["suburb_issue"] = pd.NA

    records.loc[missing, "suburb_issue"] = "missing_or_blank"
    records.loc[placeholder, "suburb_issue"] = "placeholder_or_unknown"

    # Keep a clean suburb column for actual suburb names.
    records.loc[missing | placeholder, "Suburb_clean"] = pd.NA

    # Use a separate column for the final aggregation.
    records["Suburb_group"] = records["Suburb_clean"]

    # Keep all unresolved suburb values in one reporting group.
    records.loc[
        missing | placeholder, "Suburb_group"
    ] = UNKNOWN_LABEL

    return records


def count_reports_by_suburb(records):
    """Count every service request using its suburb group."""
    counts = (
        records
        .groupby("Suburb_group")
        .size()
        .reset_index(name="report_count")
        .rename(columns={"Suburb_group": "suburb"})
        .sort_values(
            ["report_count", "suburb"],
            ascending=[False, True],
        )
        .reset_index(drop=True)
    )

    return counts


def main():
    """Clean the data, calculate suburb counts and save the results."""
    setup_logging()

    try:
        records = load_data()

        logging.info(
            "Cleaning suburb names and checking missing values..."
        )

        cleaned = clean_suburbs(records)
        counts = count_reports_by_suburb(cleaned)

        unresolved = cleaned[
            cleaned["suburb_issue"].notna()
        ].copy()

        missing_count = int(
            unresolved["suburb_issue"]
            .eq("missing_or_blank")
            .sum()
        )

        unknown_count = int(
            unresolved["suburb_issue"]
            .eq("placeholder_or_unknown")
            .sum()
        )

        total_counted = int(counts["report_count"].sum())

        if total_counted != len(records):
            raise ValueError(
                "The suburb counts do not include all records"
            )

        if counts["suburb"].isna().any():
            raise ValueError(
                "Missing suburb groups in the final counts"
            )

        CLEAN_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)

        cleaned.to_csv(CLEAN_FILE, index=False)
        counts.to_csv(RESULT_FILE, index=False)


        summary = {
            "status": "PASSED",
            "total_records": len(records),
            "aggregated_records": total_counted,
            "records_with_usable_suburbs": (
                len(records) - len(unresolved)
            ),
            "unresolved_records": len(unresolved),
            "missing_suburb_records": missing_count,
            "placeholder_suburb_records": unknown_count,
            "distinct_suburb_groups": len(counts),
        }

        SUMMARY_FILE.write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )

        logging.info(
            "Records with usable suburb names: %s",
            f"{len(records) - len(unresolved):,}",
        )
        logging.info(
            "Missing suburb names: %s",
            f"{missing_count:,}",
        )
        logging.info(
            "Unknown or placeholder suburb names: %s",
            f"{unknown_count:,}",
        )
        logging.info(
            "All %s records are included in the suburb counts.",
            f"{total_counted:,}",
        )
        logging.info(
            "Suburb cleaning and aggregation completed."
        )

    except Exception:
        logging.exception("Suburb processing failed")
        raise


if __name__ == "__main__":
    main()
