#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python environment not found."
    echo "Create .venv and install requirements.txt."
    exit 1
fi

mkdir -p logs outputs data/raw data/processed

echo "=========================================="
echo " PHDC DATA ENGINEERING ASSESSMENT"
echo "=========================================="

echo "[1/3] ArcGIS data extraction"
"$PYTHON" code/01_extract.py

echo "[2/3] Suburb cleaning and aggregation"
"$PYTHON" code/02_transform.py

echo "[3/3] Independent validation"
"$PYTHON" code/03_validate.py

echo "=========================================="
echo " PIPELINE COMPLETED SUCCESSFULLY"
echo "=========================================="

echo "Final results:"
echo "  outputs/no_power_by_suburb.csv"
echo "  outputs/validation_report.json"
