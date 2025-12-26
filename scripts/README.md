# Scripts for Qase TestRail Migration

This directory contains utility scripts for working with Qase and TestRail.

## Available Scripts

1. **compare_runs.py** - Compare test runs between TestRail and Qase
2. **clean_html_from_cases.py** - Clean HTML tags from Qase test cases

---

# Script for Comparing Test Runs Between TestRail and Qase

This script allows you to compare test runs from TestRail with test runs in Qase and identify which test runs have not been migrated.

## Description

The `compare_runs.py` script performs the following actions:

1. Loads configuration from `config.json`
2. Connects to TestRail and Qase APIs
3. Retrieves a list of all projects from both systems
4. For each project:
   - Retrieves all test runs from TestRail (including runs from test plans)
   - Retrieves all test runs from Qase
   - Compares them by name
   - Displays a list of test runs that have not been migrated
5. Saves results to a JSON file

## Requirements

All required dependencies are already listed in `requirements.txt` in the project root:

- `qase-api-client>=2.0.1`
- `requests`
- `certifi`
- and other project dependencies

## Installing Dependencies

If dependencies are not yet installed, run:

```bash
pip install -r requirements.txt
```

## Configuration

Before running the script, ensure that the `config.json` file exists and contains the correct settings:

```json
{
    "qase": {
        "api_token": "<YOUR_QASE_API_TOKEN>",
        "host": "qase.io",
        "ssl": true
    },
    "testrail": {
        "connection": "api",
        "api": {
            "host": "<TESTRAIL_HOST>",
            "user": "<TESTRAIL_USER_EMAIL>",
            "password": "<TESTRAIL_USER_PASSWORD>",
            "token": "<TESTRAIL_API_TOKEN>"
        }
    },
    "projects": {
        "import": ["Project Name 1", "Project Name 2"],
        "status": "all"
    },
    "runs": {
        "created_after": 1672524000
    }
}
```

**Important:** 
- The `projects.import` parameter defines the list of projects to compare. If an empty array `[]` is specified or the parameter is missing, all projects will be processed
- The `projects.status` parameter can be `"all"`, `"active"`, or `"completed"` - filters projects by status
- The `runs.created_after` parameter defines the minimum creation date for test runs to compare (Unix timestamp)
- If the `runs.created_after` parameter is not specified or equals 0, all test runs will be compared

## Running the Script

From the project root directory:

```bash
python scripts/compare_runs.py
```

Or from the `temp` directory:

```bash
cd scripts
python compare_runs.py
```

Or directly (if the script has execute permissions):

```bash
./scripts/compare_runs.py
```

## Script Output

The script outputs:

1. **Process Information:**
   - Number of projects found in TestRail and Qase
   - Progress of retrieving test runs for each project

2. **Comparison Results for Each Project:**
   - Total number of test runs in TestRail
   - Total number of test runs in Qase
   - Number of missing test runs
   - Number of found test runs
   - Detailed list of missing test runs with information:
     - TestRail Run ID
     - Name
     - Creation date
     - Completion date (if available)
     - Status (Active/Completed)
     - Test plan name (if run is from a plan)

3. **Summary** for all projects

## Results File

For each project, a JSON file with comparison results is created:

```
compare_runs_{PROJECT_CODE}_{TIMESTAMP}.json
```

The file contains:
- Summary information about the comparison
- List of missing test runs
- List of found test runs

## Example Output

```
================================================================================
COMPARISON RESULTS FOR PROJECT: My Test Project
================================================================================

Total TestRail runs: 150
Total Qase runs: 145
Missing runs (not migrated): 5
Found runs (migrated): 145

--------------------------------------------------------------------------------
MISSING RUNS (NOT MIGRATED TO QASE):
--------------------------------------------------------------------------------

1. TestRail Run ID: 12345
   Name: Test Run - Feature X
   Created: 2024-01-15 10:30:00
   Completed: 2024-01-15 15:45:00
   Status: Completed
   Plan: Release 1.0 (ID: 100)

...
```

## Notes

1. **Name-based Comparison:** The script compares test runs by normalized name (case-insensitive and without extra spaces). If names differ, the run will be considered missing.

2. **Test Runs from Plans:** The script also retrieves test runs that are part of test plans in TestRail.

3. **Date Filtering:** The `runs.created_after` parameter from the configuration is used to filter test runs by creation date.

4. **Projects:** The script automatically matches projects between TestRail and Qase by name. Ensure that project names match in both systems.

## Troubleshooting

### Error "Configuration file not found"
Ensure that the `config.json` file exists in the project root.

### Error "Could not fetch TestRail/Qase projects"
Check the correctness of credentials in `config.json` and API availability.

### No Project Matches
Ensure that project names in TestRail and Qase match.

### API Errors
Check logs in the `logs/` directory for detailed error information.

## License

The script is part of the qase-testrail-migration project and uses the same license.

---

# Script for Cleaning HTML Tags from Qase Test Cases

This script allows you to clean HTML tags from all test cases in a Qase project by either removing them completely or converting them to Markdown format.

## Description

The `clean_html_from_cases.py` script performs the following actions:

1. Loads configuration from `config.json`
2. Connects to Qase API
3. Retrieves all test cases from the specified project
4. For each test case:
   - Checks all text fields (title, description, preconditions, steps, custom fields) for HTML tags
   - Removes HTML tags or converts them to Markdown (depending on mode)
   - Updates the test case in Qase
5. Saves processing statistics to a JSON file

## Requirements

All required dependencies are already listed in `requirements.txt` in the project root:

- `qase-api-client>=2.0.1`
- `beautifulsoup4` (for HTML parsing)
- `html2text` (optional, for better HTML to Markdown conversion)

**Note:** The script will work with `beautifulsoup4` alone, but if `html2text` is installed, it will provide better HTML to Markdown conversion.

## Installing Dependencies

If dependencies are not yet installed, run:

```bash
pip install -r requirements.txt
```

For better HTML to Markdown conversion (optional):

```bash
pip install html2text
```

## Configuration

Before running the script, ensure that the `config.json` file exists and contains the correct Qase settings:

```json
{
    "qase": {
        "api_token": "<YOUR_QASE_API_TOKEN>",
        "host": "qase.io",
        "ssl": true
    }
}
```

## Running the Script

From the project root directory:

```bash
# Convert HTML to Markdown (default mode)
python scripts/clean_html_from_cases.py --project PROJECT_CODE

# Remove HTML tags completely
python scripts/clean_html_from_cases.py --project PROJECT_CODE --remove-html

# Dry run (show what would be changed without updating)
python scripts/clean_html_from_cases.py --project PROJECT_CODE --dry-run

# Use custom config file
python scripts/clean_html_from_cases.py --project PROJECT_CODE --config /path/to/config.json
```

Or directly (if the script has execute permissions):

```bash
./scripts/clean_html_from_cases.py --project PROJECT_CODE
```

## Command Line Arguments

- `--project` (required): Qase project code
- `--remove-html`: Remove HTML tags instead of converting to Markdown (default: convert to Markdown)
- `--dry-run`: Show what would be changed without actually updating cases
- `--config`: Path to config.json file (default: ../config.json)

## Script Output

The script outputs:

1. **Process Information:**
   - Number of test cases found in Qase
   - Progress of processing each test case
   - Details about which fields were cleaned

2. **Processing Results for Each Case:**
   - Case ID and title
   - Fields that were cleaned
   - Success/failure status

3. **Summary:**
   - Total cases processed
   - Cases with HTML tags found
   - Cases successfully updated
   - Cases skipped (no HTML tags)
   - Errors encountered

## Results File

After processing, a JSON file with statistics is created:

```
clean_html_{PROJECT_CODE}_{TIMESTAMP}.json
```

The file contains:
- Project code
- Processing mode (remove_html or convert_to_markdown)
- Processing date
- Statistics (total, processed, updated, skipped, errors)

## Example Output

```
================================================================================
HTML CLEANING FOR PROJECT: MYPROJECT
================================================================================

Fetching Qase test cases for project MYPROJECT...
  Fetched 100 cases so far...
Total Qase cases found: 150

Processing 150 test cases...
Mode: Convert HTML to Markdown
--------------------------------------------------------------------------------

[1/150] Processing case ID 123: Test Case Title...
  Case has HTML tags that need cleaning
    Cleaned description: 500 -> 450 chars
    Cleaned step action: 200 -> 180 chars
  ✓ Successfully updated case 123

[2/150] Processing case ID 124: Another Test Case...
  No HTML tags found, skipping

...

================================================================================
SUMMARY
================================================================================
Total cases: 150
Cases with HTML tags: 45
Cases updated: 45
Cases skipped (no HTML): 105
Errors: 0
================================================================================
```

## Fields Processed

The script processes the following fields in each test case:

- **Title**: Test case title
- **Description**: Test case description
- **Preconditions**: Test case preconditions
- **Steps**: Test case steps (action and expected_result fields)
- **Custom Fields**: Text custom fields (only string/text type fields)

## Notes

1. **HTML Detection:** The script detects HTML tags using regex patterns. Any text containing `<tag>` patterns will be processed.

2. **Conversion vs Removal:**
   - **Convert to Markdown (default):** Converts HTML elements to Markdown format (e.g., `<strong>` to `**bold**`, `<a href>` to `[link](url)`)
   - **Remove HTML:** Strips all HTML tags, keeping only the text content

3. **Dry Run Mode:** Use `--dry-run` to preview changes without modifying test cases in Qase. **Note:** In dry-run mode, only the first 100 test cases will be processed to allow quick preview of changes.

4. **Rate Limiting:** The script respects Qase API rate limits. For large projects, processing may take some time.

5. **Error Handling:** If an error occurs while updating a case, the script will log it and continue with the next case.

## Troubleshooting

### Error "Configuration file not found"
Ensure that the `config.json` file exists in the project root or specify the path with `--config`.

### Error "Could not fetch Qase cases"
Check the correctness of credentials in `config.json` and API availability. Verify that the project code is correct.

### API Errors
Check logs in the `logs/` directory for detailed error information. Common issues:
- Invalid API token
- Project code doesn't exist
- Rate limiting (wait and retry)

### No Cases Updated
- Verify that test cases actually contain HTML tags
- Check that you have write permissions for the project
- Use `--dry-run` to see what would be changed

## License

The script is part of the qase-testrail-migration project and uses the same license.
