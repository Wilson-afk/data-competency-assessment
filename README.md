# City of Cape Town No Power Service Requests
### PHDC Data Engineering Assessment

## Overview

This project examines service-request records classified as
`No Power` in the City of Cape Town's C3 dataset.

The assessment involved retrieving records from the ArcGIS
API, examining the suburb field, cleaning inconsistent values
and counting reports by suburb. The results were checked
against the original records and the API-reported totals.

The analysis is implemented in Python and can be reproduced
using a single command.

## Running the analysis

Clone the repository:

```bash
git clone https://github.com/Wilson-afk/data-competency-assessment.git
cd data-competency-assessment
```

Run the complete analysis:

```bash
./run_all.sh
```

The runner creates a Python 3.12 virtual environment if
needed and installs the dependencies in `requirements.txt`.

It downloads the raw data when it is missing or incomplete.
Otherwise, it reuses the saved dataset. Cleaning, aggregation
and validation are performed on every run.

Use `./run_all.sh --help` for additional instructions.

Python 3.12 and internet access for the initial download
are required. No manual download or environment activation
is needed.

## Project structure

| File or folder | Purpose |
|---|---|
| `run_all.sh` | Runs the analysis from start to finish |
| `code/01_extract.py` | Retrieves and checks API records |
| `code/02_transform.py` | Cleans suburb names and counts reports |
| `code/03_validate.py` | Checks the data and final results |
| `requirements.txt` | Python dependencies |
| `data/raw/` | Original downloaded records |
| `data/processed/` | Cleaned records |
| `outputs/` | Aggregated results and summaries |
| `logs/` | Processing and validation logs |

Generated datasets, outputs, logs and the Python environment
are excluded from version control.

## Task 1 - Data extraction

### 1.1 Finding the API

The source dataset was located on the
[City of Cape Town Open Data Portal](https://odp-cctegis.opendata.arcgis.com/datasets/cctegis::service-requests-2023-until-06-october-2026-deprecated/explore).

The ArcGIS content search API was used to identify the
dataset item. Its metadata was then examined to find the
Feature Service REST endpoint.

- ArcGIS item ID: `90711027d33940b5a06e96ad8a8f7ede`
- Source: Feature Service, non-spatial table 0

REST endpoint:

```text
https://services6.arcgis.com/nyYfO9SxHU2ChQd9/arcgis/rest/services/Service_Requests_2023_until_20_May_2026/FeatureServer/0
```

### 1.2 Inspecting the schema

The table metadata was retrieved to examine field names,
data types, record identifiers and API limits.

The source contains **14 fields**:

| Field name | ArcGIS data type |
|---|---|
| `Sub_Council` | `esriFieldTypeString` |
| `Ward` | `esriFieldTypeString` |
| `Suburb` | `esriFieldTypeString` |
| `C3_Complaint_Type` | `esriFieldTypeString` |
| `Work_Center` | `esriFieldTypeString` |
| `Notification` | `esriFieldTypeInteger` |
| `Notification_type` | `esriFieldTypeString` |
| `X_Y_Co_ordinate_1` | `esriFieldTypeDouble` |
| `X_Y_Co_ordinate_2` | `esriFieldTypeDouble` |
| `Created_On_Date` | `esriFieldTypeDate` |
| `Changed_on` | `esriFieldTypeDate` |
| `Completed_Date` | `esriFieldTypeDate` |
| `Notifications_Created` | `esriFieldTypeInteger` |
| `ObjectId` | `esriFieldTypeOID` |

The main fields used were:

- `ObjectId` - unique identifier for each record.
- `C3_Complaint_Type` - recorded complaint type.
- `Suburb` - suburb associated with the request.

The full metadata is saved to `outputs/table_schema.json`.

### 1.3 Filtering the records

The following filter was applied directly to the API:

```sql
C3_Complaint_Type = 'No Power'
```

Filtering on the server avoids downloading records belonging
to other complaint types.

The published source table contained **5,372,466**
records when checked. Of these, **584,665** were classified
as `No Power`, representing **10.88%** of the table.

### 1.4 Retrieving all matching records

The extraction script:

1. Checks the API schema and record limit.
2. Requests the total number of matching records.
3. Retrieves their ObjectIds.
4. Downloads records in batches of up to 1,000.
5. Checks the IDs and complaint type returned in each batch.
6. Compares the downloaded total with the API totals.
7. Saves the raw records to a CSV file.

The API reported a maximum of 1,000 records per request.
The matching records were retrieved in **585 batches**.

Requests include timeouts, retries and back-off for temporary
network or server errors. Unexpected API responses or record
mismatches cause the extraction to stop.

The script writes to a temporary CSV during extraction and
replaces the raw output only after the download succeeds.

The resulting dataset is saved to:

`data/raw/no_power_raw.csv`

Extraction details are saved to:

`outputs/extraction_summary.json`

## Task 2 - Initial data transformation

### 2.1 Examining the suburb field

The suburb field was examined for missing values, blank
entries, extra whitespace, inconsistent capitalisation,
placeholder values and possible spelling differences.

The original suburb values are preserved in the cleaned
dataset to allow the changes to be reviewed.

### 2.2 Cleaning decisions

The following rules were applied:

| Data quality issue | How it was handled |
|---|---|
| Leading or trailing whitespace | Removed |
| Repeated internal spaces | Replaced with one space |
| Inconsistent capitalisation | Converted to uppercase |
| Missing or blank suburb | Grouped as `UNKNOWN` |
| Recognised placeholder | Grouped as `UNKNOWN` |
| Possible spelling variation | Retained unless verified |

For example, ` philippi ` and `Philippi` are both
standardised to `PHILIPPI`.

Values such as `#`, `UNKNOWN`, `GENERIC TOWN 0000`,
`N/A`, `NA`, `NULL`, `NONE` and `UNSPECIFIED` were
treated as placeholders.

### 2.3 Missing and unknown suburb values

The cleaning identified:

| Category | Number of records |
|---|---:|
| Records with usable suburb names | 557,131 |
| Missing or blank suburb values | 1,572 |
| Unknown or placeholder suburb values | 25,962 |
| **Total No Power records** | **584,665** |

All 27,534 records without an identifiable suburb were
included in the final aggregation under one category:
`UNKNOWN`.

This includes missing, blank, unspecified and placeholder
values. The original values and their data-quality reasons
remain available in `outputs/unresolved_suburbs.csv`.

The `UNKNOWN` category does not represent a geographical
suburb. It ensures that every downloaded service-request
record is included in the final counts.

### 2.4 Spelling variations

Potential spelling variations were also identified,
including `PHILIPPI` / `PHILLIPI` and
`GUGULETU` / `GUGULETHU`.

These were not automatically merged because geographical
verification would be needed to establish that each pair
refers to the same area.

The analysis therefore uses conservative text
standardisation rather than fuzzy matching.

### 2.5 Aggregation

Records were grouped by the cleaned suburb label, including
the `UNKNOWN` category.

The number of records in each group was calculated and
sorted in descending order.

The final CSV contains two columns:

| Column | Description |
|---|---|
| `suburb` | Cleaned suburb name or unresolved category |
| `report_count` | Number of No Power service-request records |

Output: `outputs/no_power_by_suburb.csv`

## Data validation

The validation script independently checks that:

1. Required fields are present.
2. ObjectIds are present and unique.
3. All downloaded records match the `No Power` filter.
4. Downloaded record totals match the API counts.
5. Raw and cleaned records contain the same ObjectIds.
6. Missing and placeholder records are correctly identified.
7. Suburb groups can be reconstructed from the raw values.
8. Independently calculated counts match the final CSV.
9. The suburb counts add up to all extracted records.

The pipeline stops if a check fails.

Validation results are saved to
`outputs/validation_report.json`.

## Results

The analysis was completed on **19 November 2026**.

| Measure | Result |
|---|---:|
| Records in the source table | 5,372,466 |
| Records matching the No Power filter | 584,665 |
| Records with usable suburb names | 557,131 |
| Missing or blank suburb values | 1,572 |
| Unknown or placeholder suburb values | 25,962 |
| **Total records included in aggregation** | **584,665** |
| Distinct suburb groups | 5,854 |
| Validation | **PASSED** |

All **584,665** downloaded records were included in the
final suburb counts. The **27,534** records with
missing or placeholder suburb values were retained under
the `UNKNOWN` category.

The pipeline was also tested successfully from a fresh
GitHub clone, including automatic environment setup,
API extraction, cleaning and validation.

## Generated files

| File | Description |
|---|---|
| `data/raw/no_power_raw.csv` | Downloaded API records |
| `data/processed/no_power_clean.csv` | Cleaned dataset |
| `outputs/no_power_by_suburb.csv` | Final suburb counts |
| `outputs/unresolved_suburbs.csv` | Unresolved suburb records |
| `outputs/extraction_summary.json` | Extraction counts and settings |
| `outputs/transformation_summary.json` | Cleaning and aggregation summary |
| `outputs/validation_report.json` | Validation results |
| `outputs/table_schema.json` | ArcGIS table metadata |
| `logs/` | Extraction and processing logs |

Generated data and output files are not committed to Git.
They can be reproduced by running the pipeline.
