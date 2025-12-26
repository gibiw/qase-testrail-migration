#!/usr/bin/env python3
"""
Script to clean HTML tags from Qase test cases.
Gets all test cases from Qase repository and removes or converts HTML tags to markdown.
"""

import sys
import os
import json
import time
from datetime import datetime

# Add parent directory to path to import project modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.service import QaseService
from src.support import Logger, ConfigManager, html_to_markdown
from qase.api_client_v1.api.cases_api import CasesApi
from qase.api_client_v1.exceptions import ApiException

# Constants
DRY_RUN_CASE_LIMIT = 100  # Maximum number of cases to process in dry-run mode


def get_all_cases(qase_service, project_code, config, logger=None, max_cases=None):
    """
    Get all test cases from Qase for a project.
    
    Args:
        qase_service: QaseService instance
        project_code: Qase project code
        config: ConfigManager instance to check enterprise setting
        max_cases: Maximum number of cases to fetch (None for all cases)
    
    Returns:
        List of test cases with their details
    """
    cases = []
    # Set limit based on enterprise setting: 20 for enterprise, 100 for cloud
    limit = 20 if config.get('qase.enterprise') else 100
    offset = 0
    
    is_enterprise = config.get('qase.enterprise')
    print(f"Fetching Qase test cases for project {project_code}...")
    if logger:
        logger.log(f"Fetching Qase test cases for project {project_code}")
    if is_enterprise:
        print(f"  Enterprise mode: using limit={limit} and rate limiting")
        if logger:
            logger.log(f"Enterprise mode: using limit={limit} and rate limiting")
    if max_cases:
        print(f"  Limited fetch: will get maximum {max_cases} cases")
        if logger:
            logger.log(f"Limited fetch: will get maximum {max_cases} cases")
    
    try:
        api_instance = CasesApi(qase_service.client)
        
        while True:
            # Check if we've reached the maximum number of cases
            if max_cases and len(cases) >= max_cases:
                break
            
            try:
                # Adjust limit for the last request if we're near max_cases
                request_limit = limit
                if max_cases and (len(cases) + limit) > max_cases:
                    request_limit = max_cases - len(cases)
                
                api_response = api_instance.get_cases(
                    code=project_code,
                    limit=request_limit,
                    offset=offset
                )
                
                if not api_response.status or not api_response.result:
                    break
                
                if api_response.result.entities:
                    # Add cases, but respect max_cases limit
                    new_cases = [case.to_dict() for case in api_response.result.entities]
                    cases_added = len(new_cases)
                    if max_cases and (len(cases) + len(new_cases)) > max_cases:
                        # Take only what we need
                        needed = max_cases - len(cases)
                        cases.extend(new_cases[:needed])
                        cases_added = needed
                    else:
                        cases.extend(new_cases)
                    print(f"  Fetched {len(cases)} cases so far...")
                    if logger:
                        logger.log(f"Fetched {len(cases)} cases so far")
                
                # Check if we've reached max_cases or if there are no more cases
                if max_cases and len(cases) >= max_cases:
                    break
                
                # Check if there are more cases
                # If we got fewer cases than requested, there are no more
                if not api_response.result.entities or len(api_response.result.entities) < request_limit:
                    break
                
                # Increase offset by the number of cases we actually got
                offset += len(api_response.result.entities)
                
                # Add delay for enterprise to avoid rate limits
                if is_enterprise:
                    time.sleep(1)  # Small delay between requests
                    
            except ApiException as e:
                print(f"Error fetching Qase cases: {e}")
                if logger:
                    logger.log(f"Error fetching Qase cases: {e}", 'error')
                break
    except Exception as e:
        print(f"Error initializing Qase API: {e}")
        if logger:
            logger.log(f"Error initializing Qase API: {e}", 'error')
    
    print(f"Total Qase cases found: {len(cases)}")
    if logger:
        logger.log(f"Total Qase cases found: {len(cases)}")
    return cases


def has_html_tags(text):
    """
    Check if text contains HTML tags.
    
    Args:
        text: Text to check
    
    Returns:
        bool: True if text contains HTML tags
    """
    if not text or not isinstance(text, str):
        return False
    
    import re
    
    # Common HTML tags to check for
    common_html_tags = [
        'div', 'span', 'p', 'a', 'img', 'br', 'hr', 'ul', 'ol', 'li',
        'table', 'tr', 'td', 'th', 'thead', 'tbody', 'tfoot',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'strong', 'b', 'em', 'i', 'u', 's', 'strike',
        'code', 'pre', 'blockquote', 'q',
        'form', 'input', 'button', 'select', 'option', 'textarea', 'label',
        'style', 'script', 'link', 'meta', 'title', 'head', 'body', 'html',
        'iframe', 'video', 'audio', 'canvas', 'svg',
        'article', 'section', 'nav', 'header', 'footer', 'aside', 'main'
    ]
    
    # Pattern for HTML tags: <tag>, </tag>, <tag attr="value">, etc.
    # But exclude things like <variable>, <placeholder> that are not HTML
    html_pattern = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>', re.IGNORECASE)
    
    matches = html_pattern.findall(text)
    if not matches:
        return False
    
    # Check if any match is a known HTML tag
    for tag_name in matches:
        if tag_name.lower() in common_html_tags:
            return True
    
    # Also check for closing tags with known HTML tag names
    closing_tag_pattern = re.compile(r'</([a-zA-Z][a-zA-Z0-9]*)>', re.IGNORECASE)
    closing_matches = closing_tag_pattern.findall(text)
    for tag_name in closing_matches:
        if tag_name.lower() in common_html_tags:
            return True
    
    # Check for HTML comments and doctype
    if re.search(r'<!--.*?-->', text, re.DOTALL):
        return True
    if re.search(r'<!DOCTYPE', text, re.IGNORECASE):
        return True
    
    return False


def clean_case_fields(case, remove_html=False, return_originals=False):
    """
    Clean HTML tags from all fields of a test case.
    
    Args:
        case: Test case dictionary
        remove_html: If True, remove HTML tags. If False, convert to markdown.
        return_originals: If True, return dict with both original and cleaned values
    
    Returns:
        dict: Updated case data with cleaned fields, or dict with 'updated' and 'originals' if return_originals=True
    """
    updated_fields = {}
    original_fields = {}
    has_changes = False
    
    # Fields that may contain HTML
    text_fields = ['title', 'description', 'preconditions']
    
    for field in text_fields:
        if field in case and case[field]:
            original_value = case[field]
            if has_html_tags(original_value):
                cleaned_value = html_to_markdown(original_value, remove_html=remove_html)
                if cleaned_value != original_value:
                    updated_fields[field] = cleaned_value
                    if return_originals:
                        original_fields[field] = original_value
                    has_changes = True
                    if not return_originals:
                        print(f"    Cleaned {field}: {len(original_value)} -> {len(cleaned_value)} chars")
    
    # Clean steps
    if 'steps' in case and case['steps']:
        cleaned_steps = []
        original_steps = []
        steps_updated = False
        
        for step_idx, step in enumerate(case['steps']):
            step_updated = False
            # Handle both dict and object with attributes
            # First, save original step before any modifications
            if isinstance(step, dict):
                original_step = step.copy()
                cleaned_step = step.copy()
            else:
                # Convert object to dict for original
                original_step = step.to_dict() if hasattr(step, 'to_dict') else {}
                # Create a deep copy for cleaning
                import copy
                cleaned_step = copy.deepcopy(original_step)
            
            # Save original step for comparison (always save if return_originals)
            if return_originals:
                original_steps.append(original_step)
            
            # Clean action field
            action = cleaned_step.get('action') or (getattr(step, 'action', None) if not isinstance(step, dict) else None)
            if action:
                if has_html_tags(action):
                    cleaned_action = html_to_markdown(action, remove_html=remove_html)
                    if cleaned_action != action:
                        cleaned_step['action'] = cleaned_action
                        step_updated = True
                        steps_updated = True
                        if not return_originals:
                            print(f"    Cleaned step action: {len(action)} -> {len(cleaned_action)} chars")
            
            # Clean expected_result field
            expected_result = cleaned_step.get('expected_result') or (getattr(step, 'expected_result', None) if not isinstance(step, dict) else None)
            if expected_result:
                if has_html_tags(expected_result):
                    cleaned_expected = html_to_markdown(expected_result, remove_html=remove_html)
                    if cleaned_expected != expected_result:
                        cleaned_step['expected_result'] = cleaned_expected
                        step_updated = True
                        steps_updated = True
                        if not return_originals:
                            print(f"    Cleaned step expected_result: {len(expected_result)} -> {len(cleaned_expected)} chars")
            
            cleaned_steps.append(cleaned_step)
        
        if steps_updated:
            updated_fields['steps'] = cleaned_steps
            if return_originals:
                original_fields['steps'] = original_steps
            has_changes = True
    
    # Clean custom fields (text fields only)
    if 'custom_field' in case and case['custom_field']:
        cleaned_custom_fields = {}
        original_custom_fields = {}
        for field_id, field_value in case['custom_field'].items():
            if field_value and isinstance(field_value, str):
                if has_html_tags(field_value):
                    cleaned_value = html_to_markdown(field_value, remove_html=remove_html)
                    if cleaned_value != field_value:
                        cleaned_custom_fields[field_id] = cleaned_value
                        if return_originals:
                            original_custom_fields[field_id] = field_value
                        has_changes = True
                        if not return_originals:
                            print(f"    Cleaned custom field {field_id}: {len(field_value)} -> {len(cleaned_value)} chars")
                    else:
                        cleaned_custom_fields[field_id] = field_value
                else:
                    cleaned_custom_fields[field_id] = field_value
            else:
                cleaned_custom_fields[field_id] = field_value
        
        if has_changes and cleaned_custom_fields:
            updated_fields['custom_field'] = cleaned_custom_fields
            if return_originals and original_custom_fields:
                original_fields['custom_field'] = original_custom_fields
    
    if return_originals:
        return {
            'updated': updated_fields if has_changes else None,
            'originals': original_fields if has_changes else None
        } if has_changes else None
    else:
        return updated_fields if has_changes else None


def update_case(qase_service, project_code, case_id, update_data, is_enterprise=False):
    """
    Update a test case in Qase.
    
    Args:
        qase_service: QaseService instance
        project_code: Qase project code
        case_id: Test case ID
        update_data: Dictionary with fields to update
        is_enterprise: Whether this is an enterprise instance (for rate limiting)
    
    Returns:
        bool: True if update was successful
    """
    try:
        api_instance = CasesApi(qase_service.client)
        
        # Update the case - pass update_data as dict, API will handle conversion
        # Try to import TestCaseUpdate if available, otherwise use dict
        try:
            from qase.api_client_v1.models import TestCaseUpdate
            case_update = TestCaseUpdate(**update_data)
            api_response = api_instance.update_case(
                code=project_code,
                id=case_id,
                test_case_update=case_update
            )
        except ImportError:
            # Fallback: pass as dict directly
            api_response = api_instance.update_case(
                code=project_code,
                id=case_id,
                test_case_update=update_data
            )
        
        # Add delay for enterprise to avoid rate limits
        if is_enterprise:
            time.sleep(5)  # To avoid hitting rate limits
        
        return api_response.status
    except ApiException as e:
        print(f"    Error updating case {case_id}: {e}")
        return False
    except Exception as e:
        print(f"    Unexpected error updating case {case_id}: {e}")
        return False


def process_cases(qase_service, project_code, config, logger, remove_html=False, dry_run=False):
    """
    Process all test cases: get them, clean HTML, and update.
    
    Args:
        qase_service: QaseService instance
        project_code: Qase project code
        config: ConfigManager instance
        remove_html: If True, remove HTML tags. If False, convert to markdown.
        dry_run: If True, only show what would be changed without updating
    
    Returns:
        dict: Statistics about processed cases
    """
    stats = {
        'total': 0,
        'processed': 0,
        'updated': 0,
        'errors': 0,
        'skipped': 0
    }
    
    is_enterprise = config.get('qase.enterprise')
    
    # Get cases - limit to DRY_RUN_CASE_LIMIT for dry-run mode
    max_cases = DRY_RUN_CASE_LIMIT if dry_run else None
    cases = get_all_cases(qase_service, project_code, config, logger=logger, max_cases=max_cases)
    stats['total'] = len(cases)
    
    logger.log(f"Starting processing: project={project_code}, total_cases={len(cases)}, dry_run={dry_run}, remove_html={remove_html}")
    
    if not cases:
        print("No test cases found.")
        logger.log("No test cases found", 'warning')
        return stats
    
    if dry_run:
        print(f"\nDRY RUN MODE: Processing {len(cases)} test cases (limited to {DRY_RUN_CASE_LIMIT} for preview)")
        print("DRY RUN MODE: No changes will be saved.")
        logger.log(f"DRY RUN MODE: Processing {len(cases)} test cases (limited to {DRY_RUN_CASE_LIMIT} for preview)")
    else:
        print(f"\nProcessing {len(cases)} test cases...")
        logger.log(f"Processing {len(cases)} test cases")
    
    print(f"Mode: {'Remove HTML tags' if remove_html else 'Convert HTML to Markdown'}")
    print("-" * 80)
    logger.log(f"Mode: {'Remove HTML tags' if remove_html else 'Convert HTML to Markdown'}")
    
    for i, case in enumerate(cases, 1):
        case_id = case.get('id')
        case_title = case.get('title', 'Unknown')
        
        print(f"\n[{i}/{len(cases)}] Processing case ID {case_id}: {case_title}")
        logger.log(f"[{i}/{len(cases)}] Processing case ID {case_id}: {case_title}")
        
        try:
            # Clean case fields - return originals for dry-run comparison
            result = clean_case_fields(case, remove_html=remove_html, return_originals=dry_run)
            
            if result:
                stats['processed'] += 1
                print(f"  Case has HTML tags that need cleaning")
                logger.log(f"Case {case_id} has HTML tags that need cleaning")
                
                if dry_run:
                    # result is dict with 'updated' and 'originals'
                    update_data = result['updated']
                    original_data = result['originals']
                    
                    print(f"  [DRY RUN] Would update case {case_id} with fields: {list(update_data.keys())}")
                    logger.log(f"[DRY RUN] Would update case {case_id} with fields: {list(update_data.keys())}")
                    print()
                    
                    # Show comparison for each field
                    for field_name in update_data.keys():
                        if field_name == 'steps':
                            print(f"    Field: {field_name}")
                            logger.log(f"    Field: {field_name}")
                            updated_steps = update_data[field_name]
                            original_steps = original_data.get(field_name, [])
                            
                            for step_idx, updated_step in enumerate(updated_steps):
                                if step_idx < len(original_steps):
                                    orig_step = original_steps[step_idx]
                                    
                                    if 'action' in updated_step and 'action' in orig_step:
                                        if updated_step['action'] != orig_step.get('action'):
                                            print(f"      Step {step_idx + 1} - Action:")
                                            print(f"        Was: {orig_step.get('action', '')}")
                                            print(f"        Will be: {updated_step['action']}")
                                            print()
                                            logger.log(f"      Step {step_idx + 1} - Action:")
                                            logger.log(f"        Was: {orig_step.get('action', '')}")
                                            logger.log(f"        Will be: {updated_step['action']}")
                                    
                                    if 'expected_result' in updated_step and 'expected_result' in orig_step:
                                        if updated_step['expected_result'] != orig_step.get('expected_result'):
                                            print(f"      Step {step_idx + 1} - Expected Result:")
                                            print(f"        Was: {orig_step.get('expected_result', '')}")
                                            print(f"        Will be: {updated_step['expected_result']}")
                                            print()
                                            logger.log(f"      Step {step_idx + 1} - Expected Result:")
                                            logger.log(f"        Was: {orig_step.get('expected_result', '')}")
                                            logger.log(f"        Will be: {updated_step['expected_result']}")
                        elif field_name == 'custom_field':
                            print(f"    Field: {field_name}")
                            logger.log(f"    Field: {field_name}")
                            updated_custom = update_data[field_name]
                            original_custom = original_data.get(field_name, {})
                            
                            for field_id in updated_custom.keys():
                                if field_id in original_custom:
                                    print(f"      Custom Field ID {field_id}:")
                                    orig_val = original_custom[field_id]
                                    updated_val = updated_custom[field_id]
                                    print(f"        Was: {orig_val}")
                                    print(f"        Will be: {updated_val}")
                                    print()
                                    logger.log(f"      Custom Field ID {field_id}:")
                                    logger.log(f"        Was: {orig_val}")
                                    logger.log(f"        Will be: {updated_val}")
                        else:
                            # Regular text field
                            print(f"    Field: {field_name}")
                            logger.log(f"    Field: {field_name}")
                            orig_val = original_data.get(field_name, '')
                            updated_val = update_data[field_name]
                            print(f"      Was: {orig_val}")
                            print(f"      Will be: {updated_val}")
                            print()
                            logger.log(f"      Was: {orig_val}")
                            logger.log(f"      Will be: {updated_val}")
                    
                    stats['updated'] += 1
                else:
                    # Update the case - in normal mode, result is just the update_data dict
                    update_data = result if isinstance(result, dict) and 'updated' not in result else result['updated']
                    logger.log(f"Updating case {case_id} with fields: {list(update_data.keys())}")
                    success = update_case(qase_service, project_code, case_id, update_data, is_enterprise=is_enterprise)
                    if success:
                        print(f"  ✓ Successfully updated case {case_id}")
                        logger.log(f"Successfully updated case {case_id}")
                        stats['updated'] += 1
                    else:
                        print(f"  ✗ Failed to update case {case_id}")
                        logger.log(f"Failed to update case {case_id}", 'error')
                        stats['errors'] += 1
            else:
                stats['skipped'] += 1
        except Exception as e:
            print(f"  ✗ Error processing case {case_id}: {e}")
            logger.log(f"Error processing case {case_id}: {e}", 'error')
            stats['errors'] += 1
    
    return stats


def main():
    """Main function to run the HTML cleaning script."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Clean HTML tags from Qase test cases',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert HTML to markdown (default)
  python scripts/clean_html_from_cases.py --project PROJECT_CODE
  
  # Remove HTML tags completely
  python scripts/clean_html_from_cases.py --project PROJECT_CODE --remove-html
  
  # Dry run (show what would be changed)
  python scripts/clean_html_from_cases.py --project PROJECT_CODE --dry-run
        """
    )
    
    parser.add_argument(
        '--project',
        type=str,
        required=True,
        help='Qase project code'
    )
    
    parser.add_argument(
        '--remove-html',
        action='store_true',
        help='Remove HTML tags instead of converting to markdown (default: convert to markdown)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without actually updating cases'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config.json file (default: ../config.json)'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    if args.config:
        config_path = args.config
    else:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
    
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        print("Please create config.json based on config.example.json")
        sys.exit(1)
    
    config = ConfigManager(config_path)
    config.load_config()
    
    # Initialize logger
    logger = Logger(debug=True, prefix='clean_html_from_cases')
    
    # Initialize Qase service
    print("Initializing Qase service...")
    logger.log("Initializing Qase service...")
    qase_service = QaseService(config, logger)
    
    # Process cases
    print(f"\n{'=' * 80}")
    print(f"HTML CLEANING FOR PROJECT: {args.project}")
    logger.log("=" * 80)
    logger.log(f"HTML CLEANING FOR PROJECT: {args.project}")
    if config.get('qase.enterprise'):
        print(f"Enterprise mode: enabled")
        logger.log("Enterprise mode: enabled")
    print(f"{'=' * 80}")
    logger.log("=" * 80)
    
    stats = process_cases(
        qase_service,
        args.project,
        config,
        logger,
        remove_html=args.remove_html,
        dry_run=args.dry_run
    )
    
    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total cases: {stats['total']}")
    print(f"Cases with HTML tags: {stats['processed']}")
    print(f"Cases updated: {stats['updated']}")
    print(f"Cases skipped (no HTML): {stats['skipped']}")
    print(f"Errors: {stats['errors']}")
    print("=" * 80)
    
    # Log summary
    logger.log("=" * 80)
    logger.log("SUMMARY")
    logger.log(f"Total cases: {stats['total']}")
    logger.log(f"Cases with HTML tags: {stats['processed']}")
    logger.log(f"Cases updated: {stats['updated']}")
    logger.log(f"Cases skipped (no HTML): {stats['skipped']}")
    logger.log(f"Errors: {stats['errors']}")
    logger.log("=" * 80)
    
    # Save results to file
    if not args.dry_run:
        output_file = os.path.join(
            os.path.dirname(__file__),
            f'clean_html_{args.project}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        )
        
        output_data = {
            'project_code': args.project,
            'mode': 'remove_html' if args.remove_html else 'convert_to_markdown',
            'processing_date': datetime.now().isoformat(),
            'statistics': stats
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"\nResults saved to: {output_file}")


if __name__ == '__main__':
    main()

