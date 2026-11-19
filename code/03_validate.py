#!/usr/bin/env python3
"""Independently validate PHDC extraction and suburb aggregation."""

import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "outputs"
LOG = ROOT / "logs" / "validation.log"


def setup_logging():
    """Configure console and file logs."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG, mode="a"),
        ],
    )


def check(condition, message):
    """Raise an informative error when a check fails."""
    if not condition:
        raise ValueError(message)
    logging.info("PASSED: %s", message)


def main():
    """Verify extracted and transformed records independently."""
    setup_logging()

    try:
        raw = pd.read_csv(
            DATA / "raw/no_power_raw.csv",
            dtype={"ObjectId": "string"},
            low_memory=False,
        )
        clean = pd.read_csv(
            DATA / "processed/no_power_clean.csv",
            dtype={"ObjectId": "string"},
            low_memory=False,
        )
        result = pd.read_csv(OUT / "no_power_by_suburb.csv")
        excluded = pd.read_csv(
            OUT / "excluded_suburbs.csv",
            dtype={"ObjectId": "string"},
        )

        with (OUT / "extraction_summary.json").open() as f:
            extraction = json.load(f)

        check(
            raw["ObjectId"].notna().all()
            and raw["ObjectId"].is_unique,
            "Raw ObjectIds are unique and nonmissing",
        )

        check(
            raw["C3_Complaint_Type"].eq("No Power").all(),
            "All complaints are No Power",
        )

        check(
            len(raw) == len(clean)
            == extraction["extracted_records"]
            == extraction["api_count_before"]
            == extraction["api_count_after"]
            == extraction["unique_object_ids"],
            "API, raw, and cleaned record totals reconcile",
        )

        check(
            set(raw["ObjectId"]) == set(clean["ObjectId"]),
            "Raw and cleaned identifiers match",
        )

        included = clean.dropna(subset=["Suburb_clean"])
        unresolved = clean[clean["Suburb_clean"].isna()]

        check(
            set(unresolved["ObjectId"]) == set(excluded["ObjectId"])
            and excluded["ObjectId"].is_unique,
            "Excluded identifiers match unresolved records",
        )

        independent = (
            included.groupby("Suburb_clean")
            .size()
            .rename("report_count")
            .rename_axis("suburb")
            .reset_index()
            .sort_values(
                ["report_count", "suburb"],
                ascending=[False, True],
            )
            .reset_index(drop=True)
        )

        pd.testing.assert_frame_equal(
            result.reset_index(drop=True),
            independent,
            check_dtype=False,
        )
        logging.info("PASSED: Independent aggregation matches")

        check(
            int(result["report_count"].sum()) + len(excluded)
            == len(raw),
            "Aggregated and excluded records reconcile",
        )

        report = {
            "status": "PASSED",
            "api_records": extraction["api_count_after"],
            "raw_records": len(raw),
            "aggregated_records": len(included),
            "excluded_records": len(excluded),
            "distinct_suburb_labels": len(result),
        }

        (OUT / "validation_report.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        logging.info("ALL VALIDATION CHECKS PASSED")
        logging.info("Report: %s", report)

    except Exception:
        logging.exception("Independent validation FAILED")
        raise


if __name__ == "__main__":
    main()
