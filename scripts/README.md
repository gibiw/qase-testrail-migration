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
