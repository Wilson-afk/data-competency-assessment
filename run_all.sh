#!/usr/bin/env bash

# PHDC No Power Data Pipeline
#
# 1. Download raw data if it is missing or incomplete.
# 2. Clean suburb names and calculate report counts.
# 3. Validate the results.
# 4. Display execution times.

set -Eeuo pipefail

cd "$(dirname "$0")"


# Help
show_help() {
    cat <<'EOF'
PHDC No Power Data Pipeline

Usage:
  ./run_all.sh
  ./run_all.sh --help

What this pipeline does:
  1. Downloads City of Cape Town No Power service requests.
  2. Reuses previously downloaded data when complete.
  3. Cleans and standardises suburb names.
  4. Counts reports for each suburb.
  5. Validates the extracted and processed data.
  6. Displays progress and execution times.

Data extraction:
  Complaint type: No Power
  Batch size: 1,000 records

Requirements:
  Python 3.12 (dependencies are installed automatically)
  Internet access for the initial download

Main outputs:
  data/raw/no_power_raw.csv
  data/processed/no_power_clean.csv
  outputs/no_power_by_suburb.csv
  outputs/unresolved_suburbs.csv
  outputs/validation_report.json

To download fresh data again:
  Delete data/raw/no_power_raw.csv and rerun ./run_all.sh

Options:
  --help, -h    Display this help message
EOF
}

if [[ $# -eq 1 &&
      ( "$1" == "--help" || "$1" == "-h" ) ]]; then
    show_help
    exit 0
fi

if [[ $# -ne 0 ]]; then
    echo "ERROR: Unknown argument."
    echo "Run ./run_all.sh --help for instructions."
    exit 1
fi

# Environment
PYTHON=".venv/bin/python"

# Create a local Python environment when it is missing.
if [[ ! -x "$PYTHON" ]]; then
    echo "Setting up the Python environment..."

    if ! command -v python3.12 >/dev/null 2>&1; then
        echo "ERROR: Python 3.12 is required."
        exit 1
    fi

    python3.12 -m venv .venv
fi

# Install the packages required by the analysis.
echo "Checking Python dependencies..."
"$PYTHON" -m pip install --quiet -r requirements.txt

echo "Python environment ready."

mkdir -p data/raw data/processed outputs logs

format_time() {
    local seconds=$1
    printf "%dm %02ds" \
        "$((seconds / 60))" \
        "$((seconds % 60))"
}

# Check whether previously downloaded data is complete
raw_data_available() {
    "$PYTHON" - <<'PY'
import csv
import json
from pathlib import Path

raw_file = Path("data/raw/no_power_raw.csv")
summary_file = Path("outputs/extraction_summary.json")

if not raw_file.is_file() or not summary_file.is_file():
    raise SystemExit(1)

try:
    summary = json.loads(summary_file.read_text())

    expected = summary["extracted_records"]

    # Verify the saved data was extracted for this assessment.
    if summary["filter"] != "C3_Complaint_Type = 'No Power'":
        raise ValueError("Unexpected complaint filter")

    if not (
        expected == summary["unique_object_ids"]
        == summary["api_count_before"]
        == summary["api_count_after"]
    ):
        raise ValueError("Extraction totals do not match")

    # Count CSV rows to detect incomplete files.
    with raw_file.open(newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        columns = next(reader)

        required = {"ObjectId", "Suburb", "C3_Complaint_Type"}

        if not required.issubset(columns):
            raise ValueError("Missing CSV columns")

        actual = sum(1 for row in reader)

    if actual != expected:
        raise ValueError("Incomplete CSV")

except (OSError, ValueError, KeyError, StopIteration,
        csv.Error, TypeError):
    raise SystemExit(1)

raise SystemExit(0)
PY
}

# Run the pipeline
SECONDS=0

echo "========================================"
echo " City of Cape Town | No Power Service Requests"
echo "========================================"

# Step 1: Download or reuse raw data.
echo
echo "[1/3] Getting the service request data"

stage_start=$SECONDS

if raw_data_available; then
    echo "The previously downloaded dataset is available."
    echo "Using the saved data instead of downloading it again."
    extraction_status="Reused existing data"
else
    echo "No complete raw dataset was found."
    echo "Downloading No Power service requests from ArcGIS..."

    "$PYTHON" code/01_extract.py
    extraction_status="Downloaded from API"
fi

extraction_time=$((SECONDS - stage_start))

# Step 2: Clean the data.
echo
echo "[2/3] Cleaning suburb names and counting reports"

stage_start=$SECONDS
"$PYTHON" code/02_transform.py
transformation_time=$((SECONDS - stage_start))

# Step 3: Validate the results.
echo
echo "[3/3] Checking the results"

stage_start=$SECONDS
"$PYTHON" code/03_validate.py
validation_time=$((SECONDS - stage_start))

total_time=$SECONDS

# Final summary
echo
echo "========================================"
echo " Analysis completed successfully"
echo "========================================"
echo "Extraction:      $extraction_status"
echo "Extraction stage: $(format_time "$extraction_time")"
echo "Transformation:  $(format_time "$transformation_time")"
echo "Validation:      $(format_time "$validation_time")"
echo "----------------------------------------"
echo "Total time:   $(format_time "$total_time")"
echo
echo "Suburb counts: outputs/no_power_by_suburb.csv"
echo "Validation: outputs/validation_report.json"
