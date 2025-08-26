from ..support import ConfigManager, Logger

import certifi
import json

from qaseio.api_client import ApiClient
from qaseio.configuration import Configuration
from qaseio.api.authors_api import AuthorsApi
from qaseio.api.custom_fields_api import CustomFieldsApi
from qaseio.api.system_fields_api import SystemFieldsApi
from qaseio.api.projects_api import ProjectsApi
from qaseio.api.suites_api import SuitesApi
from qaseio.api.cases_api import CasesApi
from qaseio.api.runs_api import RunsApi
from qaseio.api.results_api import ResultsApi
from qaseio.api.attachments_api import AttachmentsApi
from qaseio.api.milestones_api import MilestonesApi
from qaseio.api.configurations_api import ConfigurationsApi
from qaseio.api.shared_steps_api import SharedStepsApi

from qaseio.models import TestCasebulk, SuiteCreate, MilestoneCreate, CustomFieldCreate, CustomFieldCreateValueInner, ProjectCreate, RunCreate, ResultcreateBulk, ConfigurationCreate, ConfigurationGroupCreate, SharedStepCreate, SharedStepContentCreate

from datetime import datetime

from qaseio.exceptions import ApiException


class QaseService:
    def __init__(self, config: ConfigManager, logger: Logger):
        self.config = config
        self.logger = logger

        ssl = 'http://'
        if config.get('qase.ssl') is None or config.get('qase.ssl'):
            ssl = 'https://'

        delimiter = '.'
        if config.get('qase.enterprise') is not None and config.get('qase.enterprise'):
            delimiter = '-'

        configuration = Configuration()
        configuration.api_key['TokenAuth'] = config.get('qase.api_token')
        configuration.host = f'{ssl}api{delimiter}{config.get("qase.host")}/v1'
        configuration.ssl_ca_cert = certifi.where()

        self.client = ApiClient(configuration)

    def _get_users(self, limit=100, offset=0):
        try:
            api_instance = AuthorsApi(self.client)
            # Get all authors.
            api_response = api_instance.get_authors(
                limit=limit, offset=offset, type="user")
            if api_response.status and api_response.result.entities:
                return api_response.result.entities
        except ApiException as e:
            self.logger.log(
                "Exception when calling AuthorsApi->get_authors: %s\n" % e, 'error')

    def get_all_users(self, limit=100):
        offset = 0
        while True:
            result = self._get_users(limit, offset)
            yield result
            offset += limit
            if len(result) < limit:
                break

    def get_case_custom_fields(self):
        self.logger.log('Getting custom fields from Qase')
        try:
            api_instance = CustomFieldsApi(self.client)
            # Get all custom fields.
            api_response = api_instance.get_custom_fields(
                entity='case', limit=100)
            if api_response.status and api_response.result.entities:
                return api_response.result.entities
        except ApiException as e:
            self.logger.log(
                "Exception when calling CustomFieldsApi->get_custom_fields: %s\n" % e, 'error')

    def create_custom_field(self, data) -> int:
        try:
            api_instance = CustomFieldsApi(self.client)
            # Create a custom field.
            api_response = api_instance.create_custom_field(
                custom_field_create=CustomFieldCreate(**data))
            if not api_response.status:
                self.logger.log(
                    'Error creating custom field: ' + data['title'])
            else:
                self.logger.log('Custom field created: ' + data['title'])
                return api_response.result.id
        except ApiException as e:
            self.logger.log(
                'Exception when calling CustomFieldsApi->create_custom_field: %s\n' % e, 'error')
            self.logger.log('Data being sent to API: %s' %
                            json.dumps(data, indent=2, default=str), 'error')
        return 0

    def create_configuration_group(self, project_code, title):
        try:
            api_instance = ConfigurationsApi(self.client)
            # Create a custom field.
            api_response = api_instance.create_configuration_group(
                code=project_code,
                configuration_group_create=ConfigurationGroupCreate(
                    title=title)
            )
            if not api_response.status:
                self.logger.log('Error creating configuration group: ' + title)
            else:
                self.logger.log('Configuration group created: ' + title)
                return api_response.result.id
        except ApiException as e:
            self.logger.log(
                'Exception when calling CustomFieldsApi->create_configuration_group: %s\n' % e, 'error')
        return 0

    def create_configuration(self, project_code, title, group_id):
        try:
            api_instance = ConfigurationsApi(self.client)
            # Create a custom field.
            api_response = api_instance.create_configuration(
                code=project_code,
                configuration_create=ConfigurationCreate(
                    title=title, group_id=group_id)
            )
            if not api_response.status:
                self.logger.log('Error creating configuration: ' + title)
            else:
                self.logger.log('Configuration created: ' + title)
                return api_response.result.id
        except ApiException as e:
            self.logger.log(
                'Exception when calling CustomFieldsApi->create_configuration: %s\n' % e, 'error')
        return 0

    def get_system_fields(self):
        try:
            api_instance = SystemFieldsApi(self.client)
            # Get all system fields.
            api_response = api_instance.get_system_fields()
            if api_response.status and api_response.result:
                return api_response.result
        except ApiException as e:
            self.logger.log(
                "Exception when calling SystemFieldsApi->get_system_fields: %s\n" % e, 'error')

    def prepare_custom_field_data(self, field, mappings) -> dict:
        data = {
            'title': field['label'],
            'entity': 0,  # 0 - case, 1 - run, 2 - defect,
            'type': mappings.custom_fields_type[field['type_id']],
            'value': [],
            'is_filterable': True,
            'is_visible': True,
            'is_required': False,
        }
        
        # Handle project-specific configurations
        if field.get('configs') and len(field['configs']) > 0:
            config = field['configs'][0]  # Use the first (and only) config for this project
            
            # Set required flag based on project configuration
            if config.get('options', {}).get('is_required'):
                data['is_required'] = True
            
            # Set default value based on project configuration
            if config.get('options', {}).get('default_value'):
                data['default_value'] = config['options']['default_value']
            
            # Handle project scope
            if config.get('context', {}).get('is_global', False):
                data['is_enabled_for_all_projects'] = True
                self.logger.log(f'[Qase] Creating global field: {field["label"]}')
            else:
                data['is_enabled_for_all_projects'] = False
                if config['context'].get('project_ids'):
                    data['projects_codes'] = []
                    for project_id in config['context']['project_ids']:
                        if project_id in mappings.project_map:
                            data['projects_codes'].append(mappings.project_map[project_id])
                    self.logger.log(f'[Qase] Creating project-specific field: {field["label"]} for projects: {data["projects_codes"]}')

            
            # Handle field values for selectbox, multiselect, radio types
            if field['type_id'] in [12, 6] and config.get('options', {}).get('items'):
                values = self.__split_values(config['options']['items'])
                field['qase_values'] = {}
                
                # Use a set to track unique values and avoid duplicates
                unique_values = set()
                next_id = 1
                
                for key, value in values.items():
                    value_stripped = value.strip()
                    if value_stripped not in unique_values:
                        unique_values.add(value_stripped)
                        data['value'].append(
                            CustomFieldCreateValueInner(
                                id=next_id,
                                title=value_stripped,
                            ),
                        )
                        field['qase_values'][next_id] = value_stripped
                        next_id += 1
                    else:
                        self.logger.log(f'[Qase] Skipping duplicate value: {value_stripped}')
                
                self.logger.log(f'[Qase] Field {field["label"]} has {len(unique_values)} unique values')
            else:
                self.logger.log(f'[Qase] Field {field["label"]} has no values to process')
        else:
            # Fallback for fields without configurations
            data['is_enabled_for_all_projects'] = True
            self.logger.log(f'[Qase] Creating field without configs: {field["label"]}')
            
        return data



    @staticmethod
    def __split_values(string: str, delimiter: str = ',') -> dict:
        items = string.split('\n')  # split items into a list
        result = {}
        seen_titles = set()  # Track seen titles to avoid duplicates
        
        for item in items:
            if item == '':
                continue
            # split each item into a key and a value
            key, value = item.split(delimiter)
            # Trim the title and skip empty titles
            trimmed_value = value.strip()
            if trimmed_value and trimmed_value not in seen_titles:
                result[key] = trimmed_value
                seen_titles.add(trimmed_value)
        return result

    def get_projects(self, limit=100, offset=0):
        try:
            api_instance = ProjectsApi(self.client)
            # Get all projects.
            api_response = api_instance.get_projects(limit, offset)
            if api_response.status and api_response.result:
                return api_response.result
        except ApiException as e:
            self.logger.log(
                "Exception when calling ProjectsApi->get_projects: %s\n" % e, 'error')

    def create_project(self, title, description, code, group_id=None):
        api_instance = ProjectsApi(self.client)

        data = {
            'title': title,
            'code': code,
            'description': description if description else "",
            'settings': {
                'runs': {
                    'auto_complete': False,
                }
            }
        }

        if group_id is not None:
            data['group'] = group_id

        self.logger.log(f'Creating project: {title} [{code}]')
        try:
            api_response = api_instance.create_project(
                project_create=ProjectCreate(**data)
            )
            self.logger.log(f'Project was created: {api_response.result.code}')
            return True
        except ApiException as e:
            error = json.loads(e.body)
            if error['status'] is False and error['errorFields'][0]['error'] == 'Project with the same code already exists.':
                self.logger.log(
                    f'Project with the same code already exists: {code}. Using existing project.')
                return True

            self.logger.log(
                'Exception when calling ProjectsApi->create_project: %s\n' % e, 'error')
            self.logger.log('Data being sent to API: %s' %
                            json.dumps(data, indent=2, default=str), 'error')
            return False

    def create_suite(self, code: str, title: str, description: str, parent_id=None) -> int:
        api_instance = SuitesApi(self.client)
        api_response = api_instance.create_suite(
            code=code,
            suite_create=SuiteCreate(
                title=title,
                description=description if description else "",
                preconditions="",
                # parent_id = ID in Qase
                parent_id=parent_id
            )
        )
        return api_response.result.id

    def create_cases(self, code: str, cases: list) -> bool:
        api_instance = CasesApi(self.client)

        try:
            # Check for existing cases to avoid duplicates
            existing_cases = []
            try:
                # Get existing cases to check for duplicates
                response = api_instance.get_cases(code, limit=1000)
                if response.status and response.result:
                    existing_cases = response.result
            except Exception as e:
                self.logger.log(f"Warning: Could not fetch existing cases for duplicate check: {e}", 'warning')
            
            # Filter out cases that already exist (by title)
            existing_titles = {case.title for case in existing_cases}
            new_cases = [case for case in cases if case.title not in existing_titles]
            
            if not new_cases:
                self.logger.log(f"All cases already exist in project {code}, skipping creation")
                return True
                
            if len(new_cases) < len(cases):
                self.logger.log(f"Skipping {len(cases) - len(new_cases)} duplicate cases in project {code}")
            
            # Create only new cases
            api_response = api_instance.bulk(code, TestCasebulk(cases=new_cases))
            return api_response.status
        except ApiException as e:
            self.logger.log("Exception when calling CasesApi->bulk: %s\n" % e)
            self.logger.log("Response body: %s\n" % e.body)
            self.logger.log(f"Request payload: {cases}")
        return False

    def create_run(self, run: list, project_code: str, cases: list = [], milestone_id=None):
        api_instance = RunsApi(self.client)

        # Skip empty runs - check if cases list is empty before creating run
        if not cases or len(cases) == 0:
            self.logger.log(
                f'Skipping run creation for "{run["name"]}" - no cases found', 'warning')
            return None

        data = {
            'start_time': datetime.utcfromtimestamp(run['created_on']).strftime('%Y-%m-%d %H:%M:%S'),
            'author_id': run['author_id']
        }

        if run['description']:
            data['description'] = run['description']

        if 'plan_name' in run and run['plan_name']:
            data['title'] = '['+run['plan_name']+'] '+run['name']
        else:
            data['title'] = run['name']

        if 'configurations' in run and run['configurations'] and len(run['configurations']) > 0:
            data['configurations'] = run['configurations']

        if run['is_completed']:
            # Normalize end_time - ensure end_ts >= start_ts
            if run['completed_on'] is None:
                # If completed_on is None, set it equal to created_on
                data['end_time'] = datetime.utcfromtimestamp(
                    run['created_on']).strftime('%Y-%m-%d %H:%M:%S')
            elif run['completed_on'] < run['created_on']:
                # If completed_on < created_on, log info and set end_ts = start_ts
                self.logger.log(
                    f'Run "{run["name"]}" has completed_on ({run["completed_on"]}) before created_on ({run["created_on"]}). Setting end_time equal to start_time.', 'info')
                data['end_time'] = datetime.utcfromtimestamp(
                    run['created_on']).strftime('%Y-%m-%d %H:%M:%S')
            else:
                data['end_time'] = datetime.utcfromtimestamp(
                    run['completed_on']).strftime('%Y-%m-%d %H:%M:%S')

        if milestone_id:
            data['milestone_id'] = milestone_id

        if cases and len(cases) > 0:
            data['cases'] = cases

        try:
            response = api_instance.create_run(
                code=project_code, run_create=RunCreate(**data))
            return response.result.id
        except Exception as e:
            self.logger.log(
                f'Exception when calling RunsApi->create_run for "{run["name"]}": {e}', 'error')
            self.logger.log('Data being sent to API: %s' %
                            json.dumps(data, indent=2, default=str), 'error')
            return None

    def complete_run(self, project_code, run_id):
        api_instance = RunsApi(self.client)
        try:
            api_instance.complete_run(code=project_code, id=run_id)
        except Exception as e:
            self.logger.log(
                f'Exception when calling RunsApi->complete_run: {e}', 'error')

    def send_bulk_results(self, tr_run, results, qase_run_id, qase_code, mappings, cases_map):
        res = []

        if results:
            for result in results:
                if result['status_id'] != 3:

                    elapsed = 0
                    if 'elapsed' in result and result['elapsed']:
                        if type(result['elapsed']) is str:
                            elapsed = self.convert_to_seconds(
                                result['elapsed'])
                        else:
                            elapsed = int(result['elapsed'])

                    if 'created_on' in result and result['created_on']:
                        start_time = result['created_on'] - elapsed
                        if start_time < tr_run['created_on']:
                            start_time = tr_run['created_on']
                    else:
                        start_time = tr_run['created_on']

                    if result['test_id'] in cases_map:
                        status = 'skipped'
                        if ("status_id" in result
                                and result["status_id"] is not None
                            and result["status_id"] in mappings.result_statuses
                                and mappings.result_statuses[result["status_id"]]
                            ):
                            status = mappings.result_statuses[result["status_id"]]
                        data = {
                            "case_id": cases_map[result['test_id']],
                            "status": status,
                            "time_ms": elapsed*1000,  # converting to milliseconds
                            "comment": str(result['comment'])
                        }

                        if 'attachments' in result and len(result['attachments']) > 0:
                            data['attachments'] = result['attachments']

                        if start_time:
                            data['start_time'] = start_time

                        # if (result['defects']):
                            # self.defects.append({"case_id": result["case_id"],"defects": result['defects'],"run_id": qase_run_id})

                        # if result['created_by']:
                        #     data['author_id'] = mappings.get_user_id(result['created_by'])

                        if 'custom_step_results' in result and result['custom_step_results']:
                            data['steps'] = self.prepare_result_steps(
                                result['custom_step_results'], mappings.result_statuses)

                        res.append(data)

            if len(res) > 0:
                api_results = ResultsApi(self.client)
                self.logger.log(f'Sending {len(res)} results to Qase')
                try:
                    api_results.create_result_bulk(
                        code=qase_code,
                        id=int(qase_run_id),
                        resultcreate_bulk=ResultcreateBulk(
                            results=res
                        )
                    )
                    self.logger.log(f'{len(res)} results sent to Qase')
                except Exception as e:
                    self.logger.log(
                        f'Exception when calling ResultsApi->create_result_bulk: {e}', 'error')
                    self.logger.log('Data being sent to API: %s' % json.dumps(
                        res, indent=2, default=str), 'error')

    def prepare_result_steps(self, steps, status_map) -> list:
        allowed_statuses = ['passed', 'failed', 'blocked', 'skipped']
        data = []
        try:
            for step in steps:
                status = status_map.get(str(step.get('status_id')), 'skipped')

                step_data = {
                    "status": status if status in allowed_statuses else 'skipped',
                }

                if 'actual' in step and step['actual'] is not None:
                    comment = step['actual'].strip()
                    if comment != '':
                        step_data['comment'] = comment

                data.append(step_data)
        except Exception as e:
            self.logger.log(
                f'Exception when preparing result steps: {e}', 'error')

        return data

    def convert_to_seconds(self, time_str: str) -> int:
        total_seconds = 0

        try:
            components = time_str.split()
            for component in components:
                if component.endswith('d'):
                    # 60 seconds * 60 minutes * 24 hours
                    total_seconds += int(component[:-1]) * 86400
                elif component.endswith('h'):
                    # 60 seconds * 60 minutes
                    total_seconds += int(component[:-1]) * 3600
                elif component.endswith('m'):
                    total_seconds += int(component[:-1]) * 60
                elif component.endswith('s'):
                    total_seconds += int(component[:-1])
        except Exception as e:
            self.logger.log(
                f'Exception when converting time string \'{time_str}\': {e}', 'warning')

        return total_seconds

    def upload_attachment(self, code, attachment_data):
        api_attachments = AttachmentsApi(self.client)
        try:
            response = api_attachments.upload_attachment(
                code, file=[attachment_data],
            )

            if response.status:
                return response.result[0].to_dict()
        except Exception as e:
            self.logger.log(
                f'Exception when calling AttachmentsApi->upload_attachment: {e}', 'warning')
        return None

    def create_milestone(self, project_code, title, description, status, due_date):
        data = {
            'project_code': project_code,
            'title': title
        }

        if description:
            data['description']: description

        if due_date:
            data['due_date'] = due_date

        api_instance = MilestonesApi(self.client)
        api_response = api_instance.create_milestone(
            code=project_code,
            milestone_create=MilestoneCreate(**data)
        )
        return api_response.result.id

    def create_shared_step(self, project_code, title, steps):
        inner_steps = []

        for step in steps:
            action = step['content'].strip() if 'content' in step and type(
                step['content']) is str else 'No action'

            if action == '':
                action = 'No action'
            inner_steps.append(
                SharedStepContentCreate(
                    action=action,
                    expected_result=step['expected']
                )
            )

        api_instance = SharedStepsApi(self.client)
        api_response = api_instance.create_shared_step(
            project_code, SharedStepCreate(title=title, steps=inner_steps))
        return api_response.result.hash

    def check_field_update_needed(self, field, existing_field, mappings) -> tuple[bool, dict]:
        """
        Check if a field needs to be updated by comparing TestRail configuration with existing Qase field.
        Returns (needs_update, update_data).
        """
        needs_update = False
        update_data = {}
        
        self.logger.log(f'[Qase] DEBUG: ===== STARTING FIELD UPDATE CHECK =====')
        self.logger.log(f'[Qase] DEBUG: Field: {field["label"]} (type_id: {field["type_id"]})')
        self.logger.log(f'[Qase] DEBUG: Field has qase_values: {bool(field.get("qase_values"))}')
        self.logger.log(f'[Qase] DEBUG: Field configs count: {len(field.get("configs", []))}')
        
        # Log existing field details
        self.logger.log(f'[Qase] DEBUG: Existing field ID: {getattr(existing_field, "id", "N/A")}')
        self.logger.log(f'[Qase] DEBUG: Existing field title: {getattr(existing_field, "title", "N/A")}')
        self.logger.log(f'[Qase] DEBUG: Existing field type: {getattr(existing_field, "type", "N/A")}')
        self.logger.log(f'[Qase] DEBUG: Existing field is_enabled_for_all_projects: {getattr(existing_field, "is_enabled_for_all_projects", "N/A")}')
        self.logger.log(f'[Qase] DEBUG: Existing field projects_codes: {getattr(existing_field, "projects_codes", "N/A")}')
        self.logger.log(f'[Qase] DEBUG: Existing field has value: {bool(getattr(existing_field, "value", None))}')
        
        # Check for missing values (for dropdown/multiselect fields)
        if field['type_id'] in (6, 12) and field.get('qase_values'):
            self.logger.log(f'[Qase] DEBUG: Checking for missing values in dropdown/multiselect field')
            existing_values = set()
            if hasattr(existing_field, 'value') and existing_field.value:
                for value_item in existing_field.value:
                    if hasattr(value_item, 'title'):
                        existing_values.add(value_item.title.strip())
            
            all_testrail_values = set()
            for value in field['qase_values'].values():
                all_testrail_values.add(value.strip())
            
            # Strip whitespace for accurate comparison
            all_testrail_values_stripped = {value.strip() for value in all_testrail_values}
            
            missing_values = all_testrail_values_stripped - existing_values
            self.logger.log(f'[Qase] DEBUG: Existing values: {existing_values}')
            self.logger.log(f'[Qase] DEBUG: TestRail values: {all_testrail_values_stripped}')
            self.logger.log(f'[Qase] DEBUG: Missing values: {missing_values}')
            
            if missing_values:
                needs_update = True
                update_data['missing_values'] = list(missing_values)
                self.logger.log(f'[Qase] Field {field["label"]} missing values: {missing_values}')
        
        # Check if field needs qase_values mapping update
        if field['type_id'] in (6, 12) and not field.get('qase_values'):
            self.logger.log(f'[Qase] DEBUG: Field needs qase_values mapping update')
            # Field exists but doesn't have qase_values mapping
            needs_update = True
            update_data['needs_mapping_update'] = True
            self.logger.log(f'[Qase] Field {field["label"]} needs qase_values mapping update')
        
        # Check for missing project codes
        self.logger.log(f'[Qase] DEBUG: ===== CHECKING PROJECT ASSOCIATIONS =====')
        # Always check projects, regardless of is_enabled_for_all_projects
        existing_projects = set()
        if hasattr(existing_field, 'projects_codes') and existing_field.projects_codes:
            existing_projects = set(existing_field.projects_codes)
            self.logger.log(f'[Qase] DEBUG: Found existing projects: {existing_projects}')
        else:
            self.logger.log(f'[Qase] DEBUG: No existing projects found')
        
        expected_projects = set()
        
        if field.get('configs') and len(field['configs']) > 0:
            config = field['configs'][0]
            self.logger.log(f'[Qase] DEBUG: Field config context: {config.get("context", {})}')
            self.logger.log(f'[Qase] DEBUG: Field config is_global: {config.get("context", {}).get("is_global", False)}')
            self.logger.log(f'[Qase] DEBUG: Field config project_ids: {config.get("context", {}).get("project_ids", [])}')
            
            if not config.get('context', {}).get('is_global', False):
                self.logger.log(f'[Qase] DEBUG: Field is not global, checking project associations')
                if config['context'].get('project_ids'):
                    self.logger.log(f'[Qase] DEBUG: Processing {len(config["context"]["project_ids"])} project IDs')
                    for project_id in config['context']['project_ids']:
                        self.logger.log(f'[Qase] DEBUG: Processing project_id: {project_id}')
                        if project_id in mappings.project_map:
                            project_code = mappings.project_map[project_id]
                            expected_projects.add(project_code)
                            self.logger.log(f'[Qase] DEBUG: Added project {project_code} (ID: {project_id}) to expected projects')
                        else:
                            self.logger.log(f'[Qase] DEBUG: Project ID {project_id} not found in project map')
                            self.logger.log(f'[Qase] DEBUG: Available project IDs: {list(mappings.project_map.keys())}')
                else:
                    self.logger.log(f'[Qase] DEBUG: No project_ids found in config context')
            else:
                self.logger.log(f'[Qase] DEBUG: Field is global, skipping project association check')
        else:
            self.logger.log(f'[Qase] DEBUG: No configs found for field')
        
        self.logger.log(f'[Qase] DEBUG: Expected projects: {expected_projects}')
        self.logger.log(f'[Qase] DEBUG: Existing projects: {existing_projects}')
        
        # Always add current project if field should be project-specific
        if expected_projects:
            missing_projects = expected_projects - existing_projects
            self.logger.log(f'[Qase] DEBUG: Missing projects: {missing_projects}')
            
            if missing_projects:
                needs_update = True
                update_data['missing_projects'] = list(missing_projects)
                self.logger.log(f'[Qase] Field {field["label"]} missing projects: {missing_projects}')
            else:
                self.logger.log(f'[Qase] DEBUG: No missing projects found')
            
            # Also check if field should be project-specific but is currently global
            if getattr(existing_field, 'is_enabled_for_all_projects', False):
                self.logger.log(f'[Qase] DEBUG: Field should be project-specific but is currently global')
                needs_update = True
                update_data['should_be_project_specific'] = True
                self.logger.log(f'[Qase] Field {field["label"]} should be project-specific but is currently global')
            else:
                self.logger.log(f'[Qase] DEBUG: Field is already project-specific')
        else:
            self.logger.log(f'[Qase] DEBUG: No expected projects found for this field')
        
        self.logger.log(f'[Qase] DEBUG: Final result for {field["label"]}: needs_update={needs_update}, update_data={update_data}')
        self.logger.log(f'[Qase] DEBUG: ===== ENDING FIELD UPDATE CHECK =====')
        
        return needs_update, update_data

    def update_custom_field(self, field_id: int, update_data: dict, field: dict = None, mappings = None) -> bool:
        """
        Update an existing custom field in Qase.
        """
        self.logger.log(f'[Qase] ===== STARTING FIELD UPDATE =====')
        self.logger.log(f'[Qase] Field ID: {field_id}')
        self.logger.log(f'[Qase] Update data: {update_data}')
        self.logger.log(f'[Qase] Field info: {field["label"] if field else "None"}')
        self.logger.log(f'[Qase] Mappings available: {mappings is not None}')
        
        try:
            # Get the existing field first
            self.logger.log(f'[Qase] Retrieving existing field {field_id} from Qase...')
            existing_field = self.get_custom_field(field_id)
            if not existing_field:
                self.logger.log(f'[Qase] Failed to get existing field {field_id} for update', 'error')
                return False
            
            self.logger.log(f'[Qase] Retrieved existing field: title="{getattr(existing_field, "title", "N/A")}", type="{getattr(existing_field, "type", "N/A")}", is_global={getattr(existing_field, "is_enabled_for_all_projects", "N/A")}')
            self.logger.log(f'[Qase] Existing field projects_codes: {getattr(existing_field, "projects_codes", "N/A")}')
            self.logger.log(f'[Qase] Existing field value count: {len(existing_field.value) if hasattr(existing_field, "value") and existing_field.value else 0}')
            
            # Prepare update payload
            self.logger.log(f'[Qase] Preparing update payload...')
            update_payload = {}
            
            # Always include required fields
            if hasattr(existing_field, 'title'):
                update_payload['title'] = existing_field.title
                self.logger.log(f'[Qase] Added title to payload: {existing_field.title}')
            if hasattr(existing_field, 'type'):
                update_payload['type'] = existing_field.type
                self.logger.log(f'[Qase] Added type to payload: {existing_field.type}')
            if hasattr(existing_field, 'is_enabled_for_all_projects'):
                update_payload['is_enabled_for_all_projects'] = existing_field.is_enabled_for_all_projects
                self.logger.log(f'[Qase] Added is_enabled_for_all_projects to payload: {existing_field.is_enabled_for_all_projects}')
            
            # Always include value field (required by Qase API)
            self.logger.log(f'[Qase] Processing value field...')
            if hasattr(existing_field, 'value') and existing_field.value:
                self.logger.log(f'[Qase] Value field type: {type(existing_field.value)}')
                # Handle different types of value field
                if isinstance(existing_field.value, str):
                    self.logger.log(f'[Qase] Value is string, attempting JSON parse...')
                    # If value is a string, try to parse it as JSON
                    try:
                        import json
                        parsed_value = json.loads(existing_field.value)
                        self.logger.log(f'[Qase] Successfully parsed JSON value: {parsed_value}')
                        if isinstance(parsed_value, list):
                            update_payload['value'] = parsed_value
                            self.logger.log(f'[Qase] Added parsed list value to payload: {len(parsed_value)} items')
                        else:
                            update_payload['value'] = []
                            self.logger.log(f'[Qase] Warning: Parsed value is not a list for field {field_id}, setting empty list')
                    except (json.JSONDecodeError, ValueError) as e:
                        # If parsing fails, set empty list
                        update_payload['value'] = []
                        self.logger.log(f'[Qase] Warning: Failed to parse value string for field {field_id}: {e}, setting empty list')
                elif isinstance(existing_field.value, list):
                    update_payload['value'] = existing_field.value
                    self.logger.log(f'[Qase] Added existing list value to payload: {len(existing_field.value)} items')
                else:
                    update_payload['value'] = []
                    self.logger.log(f'[Qase] Warning: Unexpected value type {type(existing_field.value)} for field {field_id}, setting empty list')
            else:
                update_payload['value'] = []
                self.logger.log(f'[Qase] No value field found, setting empty list')
            
            # Always include existing projects_codes to preserve field-project associations
            if hasattr(existing_field, 'projects_codes') and existing_field.projects_codes:
                update_payload['projects_codes'] = existing_field.projects_codes
                self.logger.log(f'[Qase] Added existing projects_codes to payload: {existing_field.projects_codes}')
            else:
                self.logger.log(f'[Qase] No existing projects_codes found')
            
            # Handle missing values
            if 'missing_values' in update_data:
                self.logger.log(f'[Qase] Processing missing values: {update_data["missing_values"]}')
                # Get existing values
                existing_values = []
                if hasattr(existing_field, 'value') and existing_field.value:
                    existing_values = existing_field.value
                    self.logger.log(f'[Qase] Found {len(existing_values)} existing values')
                
                # Add new values
                next_id = len(existing_values) + 1
                self.logger.log(f'[Qase] Starting ID counter from: {next_id}')
                for value_title in update_data['missing_values']:
                    # Check if value already exists to avoid duplicates
                    existing_value_titles = {v.title for v in existing_values}
                    if value_title not in existing_value_titles:
                        existing_values.append({
                            'id': next_id,
                            'title': value_title
                        })
                        next_id += 1
                        self.logger.log(f'[Qase] Adding value "{value_title}" to field {field_id} with ID {next_id-1}')
                    else:
                        self.logger.log(f'[Qase] Value "{value_title}" already exists in field {field_id}, skipping')
                
                update_payload['value'] = existing_values
                self.logger.log(f'[Qase] Updated value field with {len(existing_values)} total values')
            
            # Handle mapping update
            if 'needs_mapping_update' in update_data:
                self.logger.log(f'[Qase] Field {field_id} needs mapping update - this should be handled by the calling code')
                # This is a special case - we need to update the field's qase_values mapping
                # For now, we'll just log this and handle it in the calling code
            
            # Handle missing projects
            if 'missing_projects' in update_data:
                self.logger.log(f'[Qase] Processing missing projects: {update_data["missing_projects"]}')
                existing_projects = getattr(existing_field, 'projects_codes', []) or []
                self.logger.log(f'[Qase] Current projects: {existing_projects}')
                new_projects = existing_projects + update_data['missing_projects']
                self.logger.log(f'[Qase] New projects list: {new_projects}')
                update_payload['projects_codes'] = new_projects
                self.logger.log(f'[Qase] Added projects {update_data["missing_projects"]} to field {field_id}')
            
            # Handle field that should be project-specific but is currently global
            if 'should_be_project_specific' in update_data and field and mappings:
                # Get expected projects from field config
                expected_projects = []
                if field.get('configs') and len(field['configs']) > 0:
                    config = field['configs'][0]
                    if config['context'].get('project_ids'):
                        for project_id in config['context']['project_ids']:
                            if project_id in mappings.project_map:
                                expected_projects.append(mappings.project_map[project_id])
                
                if expected_projects:
                    update_payload['is_enabled_for_all_projects'] = False
                    update_payload['projects_codes'] = expected_projects
                    self.logger.log(f'[Qase] Making field {field_id} project-specific for projects: {expected_projects}')
            
            # If no updates needed, return success
            if not update_payload:
                self.logger.log(f'[Qase] No updates needed for field {field_id}')
                return True
            
            # Log final payload
            self.logger.log(f'[Qase] Final update payload: {update_payload}')
            
            # Call the API to update the field
            self.logger.log(f'[Qase] Calling Qase API to update field {field_id}...')
            api_instance = CustomFieldsApi(self.client)
            api_response = api_instance.update_custom_field(field_id, update_payload)
            
            if api_response.status:
                self.logger.log(f'[Qase] Successfully updated field {field_id}')
                self.logger.log(f'[Qase] ===== FIELD UPDATE COMPLETED SUCCESSFULLY =====')
                return True
            else:
                self.logger.log(f'[Qase] Failed to update field {field_id}: {api_response.error}', 'error')
                self.logger.log(f'[Qase] ===== FIELD UPDATE FAILED =====')
                return False
                
        except ApiException as e:
            self.logger.log(f'[Qase] API Exception when updating field {field_id}: {e}', 'error')
            self.logger.log(f'[Qase] ===== FIELD UPDATE FAILED WITH API EXCEPTION =====')
            return False
        except Exception as e:
            self.logger.log(f'[Qase] Unexpected error when updating field {field_id}: {e}', 'error')
            self.logger.log(f'[Qase] ===== FIELD UPDATE FAILED WITH UNEXPECTED ERROR =====')
            return False

    def get_custom_field(self, field_id: int):
        """
        Get a custom field by its Qase ID.
        """
        try:
            api_instance = CustomFieldsApi(self.client)
            api_response = api_instance.get_custom_field(field_id)
            
            if api_response.status and api_response.result:
                self.logger.log(f'[Qase] Retrieved field {field_id}: type={api_response.result.type}, title={api_response.result.title}')
                return api_response.result
            else:
                self.logger.log(f'[Qase] Failed to get field {field_id}: {api_response.error}', 'error')
                return None
                
        except ApiException as e:
            self.logger.log(f'[Qase] Exception when getting field {field_id}: {e}', 'error')
            return None
        except Exception as e:
            self.logger.log(f'[Qase] Unexpected error when getting field {field_id}: {e}', 'error')
            return None
