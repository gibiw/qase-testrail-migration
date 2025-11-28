#!/usr/bin/env python3
"""
Script to compare test runs between TestRail and Qase.
Shows which test runs from TestRail were not migrated to Qase.
"""

import sys
import os
import json
from datetime import datetime

# Add parent directory to path to import project modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.service import QaseService, TestrailService
from src.support import Logger, ConfigManager
from qase.api_client_v1.api.runs_api import RunsApi
from qase.api_client_v1.exceptions import ApiException


def get_testrail_runs(testrail_service, project_id, created_after=0):
    """
    Get all test runs from TestRail for a project.
    
    Args:
        testrail_service: TestrailService instance
        project_id: TestRail project ID
        created_after: Timestamp to filter runs created after this date
    
    Returns:
        List of test runs with their details
    """
    runs = []
    limit = 250
    offset = 0
    
    print(f"Fetching TestRail runs for project ID {project_id}...")
    
    while True:
        try:
            response = testrail_service.get_runs(
                project_id=project_id,
                created_after=created_after,
                limit=limit,
                offset=offset
            )
            
            if not response or 'runs' not in response:
                break
                
            runs.extend(response['runs'])
            print(f"  Fetched {len(runs)} runs so far...")
            
            if response.get('size', 0) < limit:
                break
                
            offset += limit
        except Exception as e:
            print(f"Error fetching TestRail runs: {e}")
            break
    
    # Also get runs from test plans
    print("Fetching TestRail runs from test plans...")
    plans_limit = 250
    plans_offset = 0
    
    while True:
        try:
            plans_response = testrail_service.get_plans(
                project_id=project_id,
                limit=plans_limit,
                offset=plans_offset
            )
            
            if not plans_response or 'plans' not in plans_response:
                break
            
            for plan in plans_response['plans']:
                try:
                    plan_details = testrail_service.get_plan(plan['id'])
                    if plan_details and 'entries' in plan_details:
                        for entry in plan_details.get('entries', []):
                            for run in entry.get('runs', []):
                                # Add plan name to run for identification
                                run['plan_name'] = plan['name']
                                run['plan_id'] = plan['id']
                                runs.append(run)
                except Exception as e:
                    print(f"  Error fetching plan {plan['id']}: {e}")
                    continue
            
            if plans_response.get('size', 0) < plans_limit:
                break
                
            plans_offset += plans_limit
        except Exception as e:
            print(f"Error fetching TestRail plans: {e}")
            break
    
    print(f"Total TestRail runs found: {len(runs)}")
    return runs


def get_qase_runs(qase_service, project_code):
    """
    Get all test runs from Qase for a project.
    
    Args:
        qase_service: QaseService instance
        project_code: Qase project code
    
    Returns:
        List of test runs with their details
    """
    runs = []
    limit = 100
    offset = 0
    
    print(f"Fetching Qase runs for project {project_code}...")
    
    try:
        api_instance = RunsApi(qase_service.client)
        
        while True:
            try:
                api_response = api_instance.get_runs(
                    code=project_code,
                    limit=limit,
                    offset=offset
                )
                
                if not api_response.status or not api_response.result:
                    break
                
                if api_response.result.entities:
                    runs.extend([run.to_dict() for run in api_response.result.entities])
                    print(f"  Fetched {len(runs)} runs so far...")
                
                # Check if there are more runs
                if not api_response.result.entities or len(api_response.result.entities) < limit:
                    break
                
                offset += limit
            except ApiException as e:
                print(f"Error fetching Qase runs: {e}")
                break
    except Exception as e:
        print(f"Error initializing Qase API: {e}")
    
    print(f"Total Qase runs found: {len(runs)}")
    return runs


def normalize_run_name(name):
    """
    Normalize run name for comparison.
    Removes extra spaces and converts to lowercase.
    
    Args:
        name: Run name string
    
    Returns:
        Normalized run name
    """
    if not name:
        return ""
    return " ".join(name.split()).lower().strip()


def compare_runs(testrail_runs, qase_runs):
    """
    Compare TestRail runs with Qase runs and find missing ones.
    
    Args:
        testrail_runs: List of TestRail runs
        qase_runs: List of Qase runs
    
    Returns:
        Dictionary with comparison results
    """
    # Remove duplicates from TestRail runs (same ID)
    seen_tr_ids = set()
    unique_tr_runs = []
    for tr_run in testrail_runs:
        tr_id = tr_run.get('id')
        if tr_id and tr_id not in seen_tr_ids:
            seen_tr_ids.add(tr_id)
            unique_tr_runs.append(tr_run)
    
    # Create a set of normalized Qase run names for quick lookup
    qase_run_names = set()
    qase_runs_by_name = {}
    
    for qase_run in qase_runs:
        name = qase_run.get('title', '')
        normalized_name = normalize_run_name(name)
        qase_run_names.add(normalized_name)
        if normalized_name not in qase_runs_by_name:
            qase_runs_by_name[normalized_name] = []
        qase_runs_by_name[normalized_name].append(qase_run)
    
    missing_runs = []
    found_runs = []
    
    for tr_run in unique_tr_runs:
        tr_name = tr_run.get('name', '')
        normalized_tr_name = normalize_run_name(tr_name)
        
        # Check if run exists in Qase
        if normalized_tr_name in qase_run_names:
            found_runs.append({
                'testrail_id': tr_run.get('id'),
                'testrail_name': tr_name,
                'testrail_created_on': tr_run.get('created_on'),
                'qase_runs': qase_runs_by_name[normalized_tr_name]
            })
        else:
            missing_runs.append({
                'testrail_id': tr_run.get('id'),
                'name': tr_name,
                'created_on': tr_run.get('created_on'),
                'completed_on': tr_run.get('completed_on'),
                'is_completed': tr_run.get('is_completed'),
                'plan_name': tr_run.get('plan_name'),
                'plan_id': tr_run.get('plan_id')
            })
    
    return {
        'missing': missing_runs,
        'found': found_runs,
        'total_testrail': len(unique_tr_runs),
        'total_qase': len(qase_runs)
    }


def format_timestamp(timestamp):
    """
    Format Unix timestamp to readable date string.
    
    Args:
        timestamp: Unix timestamp
    
    Returns:
        Formatted date string
    """
    if not timestamp:
        return "N/A"
    try:
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return str(timestamp)


def print_results(results, project_name):
    """
    Print comparison results in a readable format.
    
    Args:
        results: Dictionary with comparison results
        project_name: Name of the project
    """
    print("\n" + "=" * 80)
    print(f"COMPARISON RESULTS FOR PROJECT: {project_name}")
    print("=" * 80)
    print(f"\nTotal TestRail runs: {results['total_testrail']}")
    print(f"Total Qase runs: {results['total_qase']}")
    print(f"Missing runs (not migrated): {len(results['missing'])}")
    print(f"Found runs (migrated): {len(results['found'])}")
    
    if results['missing']:
        print("\n" + "-" * 80)
        print("MISSING RUNS (NOT MIGRATED TO QASE):")
        print("-" * 80)
        for i, run in enumerate(results['missing'], 1):
            print(f"\n{i}. TestRail Run ID: {run['testrail_id']}")
            print(f"   Name: {run['name']}")
            print(f"   Created: {format_timestamp(run['created_on'])}")
            if run.get('completed_on'):
                print(f"   Completed: {format_timestamp(run['completed_on'])}")
            print(f"   Status: {'Completed' if run.get('is_completed') else 'Active'}")
            if run.get('plan_name'):
                print(f"   Plan: {run['plan_name']} (ID: {run.get('plan_id')})")
    else:
        print("\n✓ All TestRail runs have been migrated to Qase!")
    
    print("\n" + "=" * 80)


def save_results_to_file(results, project_name, output_file):
    """
    Save comparison results to a JSON file.
    
    Args:
        results: Dictionary with comparison results
        project_name: Name of the project
        output_file: Path to output file
    """
    output_data = {
        'project_name': project_name,
        'comparison_date': datetime.now().isoformat(),
        'summary': {
            'total_testrail_runs': results['total_testrail'],
            'total_qase_runs': results['total_qase'],
            'missing_runs_count': len(results['missing']),
            'found_runs_count': len(results['found'])
        },
        'missing_runs': results['missing'],
        'found_runs': results['found']
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nResults saved to: {output_file}")


def main():
    """Main function to run the comparison."""
    # Load configuration
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        print("Please create config.json based on config.example.json")
        sys.exit(1)
    
    config = ConfigManager(config_path)
    config.load_config()
    
    # Initialize logger
    logger = Logger(debug=True, prefix='compare_runs')
    
    # Initialize services
    print("Initializing services...")
    testrail_service = TestrailService(config, logger)
    qase_service = QaseService(config, logger)
    
    # Get project information
    print("\nFetching projects...")
    try:
        testrail_projects_response = testrail_service.get_projects(limit=250, offset=0)
        if not testrail_projects_response or 'projects' not in testrail_projects_response:
            print("Error: Could not fetch TestRail projects")
            sys.exit(1)
        
        all_testrail_projects = testrail_projects_response['projects']
        print(f"Found {len(all_testrail_projects)} TestRail projects")
        
        # Filter projects based on config
        projects_to_import = config.get('projects.import') or []
        project_status = config.get('projects.status') or 'all'
        
        # Filter TestRail projects
        testrail_projects = []
        for tr_project in all_testrail_projects:
            tr_name = tr_project.get('name', '')
            is_completed = tr_project.get('is_completed', False)
            
            # Check if project should be imported based on config
            should_import = True
            
            # Check if project is in import list
            if projects_to_import and tr_name not in projects_to_import:
                should_import = False
            
            # Check project status
            if project_status == 'active' and is_completed:
                should_import = False
            elif project_status == 'completed' and not is_completed:
                should_import = False
            
            if should_import:
                testrail_projects.append(tr_project)
        
        if not testrail_projects:
            print(f"\nNo projects match the filter criteria:")
            print(f"  Import list: {projects_to_import if projects_to_import else 'all projects'}")
            print(f"  Status: {project_status}")
            sys.exit(1)
        
        print(f"Filtered to {len(testrail_projects)} project(s) based on config:")
        for tr_project in testrail_projects:
            print(f"  - {tr_project.get('name', 'Unknown')} (ID: {tr_project.get('id')})")
        
        # Get Qase projects
        qase_projects_result = qase_service.get_projects(limit=100, offset=0)
        if not qase_projects_result:
            print("Error: Could not fetch Qase projects")
            sys.exit(1)
        
        qase_projects = qase_projects_result.entities if hasattr(qase_projects_result, 'entities') and qase_projects_result.entities else []
        print(f"Found {len(qase_projects)} Qase projects")
        
    except Exception as e:
        print(f"Error fetching projects: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Create project mapping (TestRail ID -> Qase code)
    # This assumes projects have been migrated and names match
    project_mapping = {}
    for tr_project in testrail_projects:
        tr_name = tr_project.get('name', '')
        for qase_project in qase_projects:
            # Handle both object attributes and dict-like access
            if hasattr(qase_project, 'to_dict'):
                qase_dict = qase_project.to_dict()
                qase_title = qase_dict.get('title', '')
                qase_code = qase_dict.get('code', '')
            else:
                qase_title = getattr(qase_project, 'title', '')
                qase_code = getattr(qase_project, 'code', '')
            
            if qase_title == tr_name and qase_code:
                project_mapping[tr_project['id']] = qase_code
                print(f"Matched project: {tr_name} (TestRail ID: {tr_project['id']} -> Qase Code: {qase_code})")
                break
        
        if tr_project['id'] not in project_mapping:
            print(f"Warning: Could not find matching Qase project for TestRail project: {tr_name} (ID: {tr_project['id']})")
    
    if not project_mapping:
        print("\nError: No matching projects found between TestRail and Qase.")
        print("Please ensure projects have been migrated and names match.")
        sys.exit(1)
    
    print(f"\nFound {len(project_mapping)} matching project(s) to compare")
    
    # Get created_after filter from config
    created_after = config.get('runs.created_after') or 0
    
    # Compare runs for each project
    all_results = {}
    
    for tr_project_id, qase_code in project_mapping.items():
        tr_project = next((p for p in testrail_projects if p['id'] == tr_project_id), None)
        if not tr_project:
            continue
        
        project_name = tr_project.get('name', f'Project {tr_project_id}')
        print(f"\n{'=' * 80}")
        print(f"Processing project: {project_name}")
        print(f"TestRail ID: {tr_project_id}, Qase Code: {qase_code}")
        print(f"{'=' * 80}")
        
        # Get runs from both systems
        testrail_runs = get_testrail_runs(testrail_service, tr_project_id, created_after)
        qase_runs = get_qase_runs(qase_service, qase_code)
        
        # Compare runs
        results = compare_runs(testrail_runs, qase_runs)
        all_results[project_name] = results
        
        # Print results
        print_results(results, project_name)
        
        # Save results to file
        output_file = os.path.join(
            os.path.dirname(__file__),
            f'compare_runs_{qase_code}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        )
        save_results_to_file(results, project_name, output_file)
    
    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY FOR ALL PROJECTS")
    print("=" * 80)
    total_missing = sum(len(r['missing']) for r in all_results.values())
    total_found = sum(len(r['found']) for r in all_results.values())
    total_tr = sum(r['total_testrail'] for r in all_results.values())
    total_qase = sum(r['total_qase'] for r in all_results.values())
    
    print(f"\nTotal TestRail runs across all projects: {total_tr}")
    print(f"Total Qase runs across all projects: {total_qase}")
    print(f"Total missing runs: {total_missing}")
    print(f"Total found runs: {total_found}")
    print("=" * 80)


if __name__ == '__main__':
    main()

