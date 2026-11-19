#!/usr/bin/env python3
"""Clean and aggregate Cape Town C3 No Power reports by suburb."""

import json
import logging
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/raw/no_power_raw.csv"
OUTPUT_DIR = ROOT / "outputs"
PROCESSED_DIR = ROOT / "data/processed"
LOG_FILE = ROOT / "logs/transformation.log"

LOGGER = logging.getLogger("cider.transform")

PLACEHOLDERS = {
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
    """Configure terminal and file logging."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, mode="a"),
        ],
    )


def load_data():
    """Load records and verify required input fields."""
    if not INPUT.is_file():
        raise FileNotFoundError(f"Missing input: {INPUT}")

    df = pd.read_csv(
        INPUT,
        dtype={
            "ObjectId": "string",
            "Suburb": "string",
            "C3_Complaint_Type": "string",
        },
        low_memory=False,
    )

    required = {
        "ObjectId",
        "Suburb",
        "C3_Complaint_Type",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    if df["ObjectId"].isna().any():
        raise ValueError("Missing ObjectId values")

    if df["ObjectId"].duplicated().any():
        raise ValueError("Duplicate ObjectId values")

    if not df["C3_Complaint_Type"].eq("No Power").all():
        raise ValueError("Unexpected complaint types")

    LOGGER.info("Loaded and verified %d records", len(df))
    return df


def clean_suburbs(df):
    """Standardise labels and classify unresolved locations."""
    df = df.copy()

    df["Suburb_original"] = df["Suburb"]

    df["Suburb_clean"] = (
        df["Suburb"]
        .fillna("")
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
    )

    df["exclusion_reason"] = pd.NA

    blank = df["Suburb_clean"].eq("")
    placeholder = df["Suburb_clean"].isin(PLACEHOLDERS)

    df.loc[blank, "exclusion_reason"] = "missing_or_blank"
    df.loc[
        placeholder & ~blank,
        "exclusion_reason",
    ] = "placeholder_or_unknown"

    df.loc[
        df["exclusion_reason"].notna(),
        "Suburb_clean",
    ] = pd.NA

    LOGGER.info(
        "Valid suburb records: %d",
        df["Suburb_clean"].notna().sum(),
    )

    LOGGER.info(
        "Unresolved suburb records: %d",
        df["Suburb_clean"].isna().sum(),
    )

    return df


def aggregate(df):
    """Count reports by cleaned suburb, highest count first."""
    return (
        df.dropna(subset=["Suburb_clean"])
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


def validate(df, summary, excluded):
    """Reconcile all input, included and excluded records."""
    total = len(df)
    included = int(summary["report_count"].sum())
    omitted = len(excluded)

    if included + omitted != total:
        raise ValueError(
            f"Reconciliation failed: "
            f"{included} + {omitted} != {total}"
        )

    if summary["suburb"].duplicated().any():
        raise ValueError("Duplicate suburbs in output")

    if not summary["report_count"].is_monotonic_decreasing:
        raise ValueError("Counts are not sorted descending")

    LOGGER.info(
        "Reconciliation PASSED: %d + %d = %d",
        included, omitted, total,
    )

    return {
        "status": "PASSED",
        "total_records": total,
        "aggregated_records": included,
        "excluded_records": omitted,
        "distinct_suburbs": len(summary),
        "exclusions_by_reason": {
            str(k): int(v)
            for k, v in excluded[
                "exclusion_reason"
            ].value_counts().items()
        },
    }


def main():
    """Execute cleaning, aggregation and validation."""
    setup_logging()

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

        df = load_data()
        cleaned = clean_suburbs(df)

        excluded = cleaned[
            cleaned["exclusion_reason"].notna()
        ].copy()

        summary = aggregate(cleaned)
        report = validate(cleaned, summary, excluded)

        cleaned.to_csv(
            PROCESSED_DIR / "no_power_clean.csv",
            index=False,
        )

        excluded[
            ["ObjectId", "Suburb_original", "exclusion_reason"]
        ].to_csv(
            OUTPUT_DIR / "excluded_suburbs.csv",
            index=False,
        )

        summary.to_csv(
            OUTPUT_DIR / "no_power_by_suburb.csv",
            index=False,
        )

        (OUTPUT_DIR / "transformation_summary.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        LOGGER.info("Transformation validation PASSED")
        LOGGER.info("Summary: %s", report)

    except Exception:
        LOGGER.exception("Transformation failed")
        raise


if __name__ == "__main__":
    main()
