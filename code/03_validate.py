#!/usr/bin/env python3
"""
Check the downloaded records and final suburb counts.

Verifies record IDs, complaint types, missing suburb values
and the final aggregation against the original dataset.
"""

import json
import logging
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_DIR / "data"
OUTPUT_DIR = PROJECT_DIR / "outputs"
LOG_FILE = PROJECT_DIR / "logs/validation.log"

UNKNOWN_LABEL = "UNKNOWN"

# Confirmed spelling and spacing corrections.
SUBURB_CORRECTIONS = {
    "PHILLIPI": "PHILIPPI",
    "GUGULETHU": "GUGULETU",
    "FISHHOEK": "FISH HOEK",
}


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


def check(condition, message):
    """Stop if a validation check fails."""
    if not condition:
        raise ValueError(message)


def validate_data():
    """Check the downloaded data and independently verify the counts."""
    logging.info("Loading the data and checking the results...")

    raw = pd.read_csv(
        DATA_DIR / "raw/no_power_raw.csv",
        dtype={"ObjectId": "string", "Suburb": "string"},
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

    unresolved = pd.read_csv(
        OUTPUT_DIR / "unresolved_suburbs.csv",
        dtype={"ObjectId": "string"},
    )

    extraction = json.loads(
        (OUTPUT_DIR / "extraction_summary.json").read_text()
    )

    # Check that the expected data fields are present.
    check(
        {"ObjectId", "Suburb", "C3_Complaint_Type"}.issubset(
            raw.columns
        ),
        "Required raw-data columns are missing",
    )

    check(
        {
            "ObjectId",
            "Suburb_original",
            "Suburb_clean",
            "Suburb_group",
            "suburb_issue",
        }.issubset(cleaned.columns),
        "Required cleaned-data columns are missing",
    )

    check(
        list(counts.columns) == ["suburb", "report_count"],
        "Unexpected columns in the suburb counts",
    )

    check(
        {"ObjectId", "Suburb_original", "suburb_issue"}.issubset(
            unresolved.columns
        ),
        "Required unresolved-data columns are missing",
    )

    # Check unique IDs and the complaint filter.
    check(
        raw["ObjectId"].notna().all()
        and raw["ObjectId"].is_unique,
        "Missing or duplicate ObjectIds in raw data",
    )

    check(
        cleaned["ObjectId"].notna().all()
        and cleaned["ObjectId"].is_unique,
        "Missing or duplicate ObjectIds in cleaned data",
    )

    check(
        raw["C3_Complaint_Type"].eq("No Power").all(),
        "Some records do not match the No Power filter",
    )

    check(
        extraction["filter"] == "C3_Complaint_Type = 'No Power'",
        "The extraction summary uses a different filter",
    )

    expected_total = extraction["api_count_before"]

    check(
        len(raw)
        == len(cleaned)
        == expected_total
        == extraction["unique_object_ids"]
        == extraction["extracted_records"]
        == extraction["api_count_after"],
        "The API and downloaded record totals do not match",
    )

    check(
        set(raw["ObjectId"]) == set(cleaned["ObjectId"]),
        "Raw and cleaned record IDs do not match",
    )

    logging.info(
        "The %s downloaded records match the API totals.",
        f"{len(raw):,}",
    )

    # Reconstruct suburb groups from the original raw values.
    original_suburbs = (
        raw["Suburb"]
        .fillna("")
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
    )

    missing = original_suburbs.eq("")
    placeholder = (
        original_suburbs.isin(PLACEHOLDER_VALUES)
        | original_suburbs.str.fullmatch(
            r"\d+|[^A-Z0-9\s]+", na=False
        )
    )

    expected_groups = original_suburbs.replace(SUBURB_CORRECTIONS)
    expected_groups.loc[missing | placeholder] = UNKNOWN_LABEL

    # Compare labels by ObjectId, not by CSV row position.
    expected_by_id = pd.Series(
        expected_groups.to_numpy(),
        index=raw["ObjectId"].to_numpy(),
    )

    actual_by_id = pd.Series(
        cleaned["Suburb_group"].to_numpy(),
        index=cleaned["ObjectId"].to_numpy(),
    )

    check(
        expected_by_id.sort_index().equals(
            actual_by_id.sort_index()
        ),
        "Cleaned suburb groups do not match the raw data",
    )

    # Check the unresolved records and their reasons.
    expected_issues = pd.Series(
        pd.NA,
        index=raw["ObjectId"].to_numpy(),
        dtype="string",
    )

    expected_issues.loc[
        raw.loc[missing, "ObjectId"].to_numpy()
    ] = "missing_or_blank"

    expected_issues.loc[
        raw.loc[placeholder, "ObjectId"].to_numpy()
    ] = "placeholder_or_unknown"

    actual_issues = pd.Series(
        cleaned["suburb_issue"].to_numpy(),
        index=cleaned["ObjectId"].to_numpy(),
        dtype="string",
    )

    check(
        expected_issues.sort_index().equals(
            actual_issues.sort_index()
        ),
        "Suburb issue reasons do not match the raw data",
    )

    expected_unresolved_ids = set(
        raw.loc[missing | placeholder, "ObjectId"]
    )

    check(
        unresolved["ObjectId"].notna().all()
        and unresolved["ObjectId"].is_unique,
        "Missing or duplicate IDs in unresolved data",
    )

    check(
        set(unresolved["ObjectId"]) == expected_unresolved_ids,
        "The unresolved record list is incomplete",
    )

    # Independently calculate counts from the raw dataset.
    independent_counts = (
        expected_groups
        .value_counts()
        .rename_axis("suburb")
        .reset_index(name="report_count")
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

    logging.info(
        "The suburb counts match a separate calculation."
    )

    # Confirm all records are included in the final totals.
    check(
        counts["suburb"].notna().all()
        and counts["suburb"].is_unique,
        "Missing or duplicate suburb groups",
    )

    check(
        counts["report_count"].notna().all()
        and (counts["report_count"] > 0).all()
        and (counts["report_count"] % 1 == 0).all(),
        "Invalid report counts",
    )

    total_counted = int(counts["report_count"].sum())
    missing_count = int(missing.sum())
    unknown_count = int(placeholder.sum())

    check(
        total_counted == len(raw),
        "Not all records were included in the final counts",
    )

    unknown_in_counts = counts.loc[
        counts["suburb"].eq(UNKNOWN_LABEL), "report_count"
    ].sum()

    check(
        int(unknown_in_counts) == missing_count + unknown_count,
        "Unknown suburb total does not match unresolved records",
    )

    logging.info(
        "Missing suburb records included: %s",
        f"{missing_count:,}",
    )

    logging.info(
        "Placeholder suburb records included: %s",
        f"{unknown_count:,}",
    )

    logging.info(
        "All %s service requests are included in the counts.",
        f"{total_counted:,}",
    )

    return {
        "status": "PASSED",
        "api_records": expected_total,
        "raw_records": len(raw),
        "aggregated_records": total_counted,
        "records_with_usable_suburbs": (
            total_counted - missing_count - unknown_count
        ),
        "missing_suburb_records": missing_count,
        "placeholder_suburb_records": unknown_count,
        "unresolved_records": len(unresolved),
        "distinct_suburb_groups": len(counts),
    }


def main():
    """Run the checks and save a validation report."""
    setup_logging()

    try:
        report = validate_data()

        report_file = OUTPUT_DIR / "validation_report.json"

        report_file.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        logging.info("All validation checks passed.")

    except Exception:
        logging.exception("Validation failed")
        raise


if __name__ == "__main__":
    main()
