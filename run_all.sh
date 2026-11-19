#!/usr/bin/env bash

# PHDC Data Engineering Pipeline
#
# This script:
# 1. Checks that the Python environment exists.
# 2. Downloads No Power records from the ArcGIS API.
# 3. Cleans suburb names and calculates report counts.
# 4. Validates the extracted and processed records.
# 5. Stops execution if a stage fails.
#
# Usage:
#   ./run_all.sh                 Run the complete pipeline
#   ./run_all.sh --skip-download Reuse existing extracted data
#
set -Eeuo pipefail

# Move to the project directory.
cd "$(dirname "$0")"

PYTHON=".venv/bin/python"

# Make sure the Python environment exists.
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python environment not found."
    echo "Create .venv and install requirements.txt."
    exit 1
fi

mkdir -p data/raw data/processed outputs logs

echo "=================================="
echo " PHDC NO POWER DATA PIPELINE"
echo "=================================="

# Step 1: Download data unless skip-download is requested.
if [[ "${1:-}" == "--skip-download" ]]; then
    echo "[1/3] Reusing existing extracted data"

    if [[ ! -f data/raw/no_power_raw.csv ||
          ! -f outputs/extraction_summary.json ]]; then
        echo "ERROR: Extracted data or extraction summary missing."
        exit 1
    fi
elif [[ $# -eq 0 ]]; then
    echo "[1/3] Downloading records"
    "$PYTHON" code/01_extract.py
else
    echo "ERROR: Unknown argument: $1"
    echo "Usage: ./run_all.sh [--skip-download]"
    exit 1
fi

echo "[2/3] Cleaning and counting reports"
"$PYTHON" code/02_transform.py

echo "[3/3] Validating results"
"$PYTHON" code/03_validate.py

echo "=================================="
echo " PIPELINE COMPLETED SUCCESSFULLY"
echo "=================================="
echo "Results: outputs/no_power_by_suburb.csv"
echo "Validation: outputs/validation_report.json"
