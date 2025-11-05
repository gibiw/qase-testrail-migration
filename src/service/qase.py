from ..support import ConfigManager, Logger, format_links_as_markdown

import certifi
import json


from qase.api_client_v1.api_client import ApiClient
from qase.api_client_v1.configuration import Configuration
from qase.api_client_v1.api.authors_api import AuthorsApi
from qase.api_client_v1.api.custom_fields_api import CustomFieldsApi
from qase.api_client_v1.api.system_fields_api import SystemFieldsApi
from qase.api_client_v1.api.projects_api import ProjectsApi
from qase.api_client_v1.api.suites_api import SuitesApi
from qase.api_client_v1.api.cases_api import CasesApi
from qase.api_client_v1.api.runs_api import RunsApi
from qase.api_client_v1.api.results_api import ResultsApi
from qase.api_client_v1.api.attachments_api import AttachmentsApi
from qase.api_client_v1.api.milestones_api import MilestonesApi
from qase.api_client_v1.api.configurations_api import ConfigurationsApi
from qase.api_client_v1.api.shared_steps_api import SharedStepsApi

from qase.api_client_v1.models import TestCasebulk, SuiteCreate, MilestoneCreate, CustomFieldCreate, CustomFieldCreateValueInner, ProjectCreate, RunCreate, ResultCreateBulk, ConfigurationCreate, ConfigurationGroupCreate, SharedStepCreate, SharedStepContentCreate

# Import for new API v2 client
from qase.api_client_v2.api_client import ApiClient as ApiClientV2
from qase.api_client_v2.configuration import Configuration as ConfigurationV2
from qase.api_client_v2.api.results_api import ResultsApi as ResultsApiV2
from qase.api_client_v2.models.create_results_request_v2 import CreateResultsRequestV2
from qase.api_client_v2.models.result_create import ResultCreate as ResultCreateV2
from qase.api_client_v2.models.result_execution import ResultExecution
from qase.api_client_v2.models.result_step import ResultStep
from qase.api_client_v2.models.result_step_data import ResultStepData
from qase.api_client_v2.models.result_step_execution import ResultStepExecution
from qase.api_client_v2.models.result_step_status import ResultStepStatus

from datetime import datetime

from qase.api_client_v1.exceptions import ApiException


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
        
        # Initialize API v2 client with minimal configuration to avoid SSL issues
        configuration_v2 = ConfigurationV2()
        configuration_v2.api_key['TokenAuth'] = config.get('qase.api_token')
        configuration_v2.host = f'{ssl}api{delimiter}{config.get("qase.host")}/v2'
        configuration_v2.ssl_ca_cert = certifi.where()
        
        # Create client with minimal configuration
        self.client_v2 = ApiClientV2(configuration_v2)
        
        # Add custom header for migration
        self.client_v2.default_headers['migration'] = 'true'

    def _get_users(self, limit=100, offset=0):
        try:
            api_instance = AuthorsApi(self.client)
            # Get all authors.
            api_response = api_instance.get_authors(limit=limit, offset=offset, type="user")
            if api_response.status and api_response.result.entities:
                return api_response.result.entities
        except ApiException as e:
            self.logger.log("Exception when calling AuthorsApi->get_authors: %s\n" % e, 'error')

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
            api_response = api_instance.get_custom_fields(entity='case', limit=100)
            if api_response.status and api_response.result.entities:
                return api_response.result.entities
        except ApiException as e:
            self.logger.log("Exception when calling CustomFieldsApi->get_custom_fields: %s\n" % e, 'error')

    def create_custom_field(self, data) -> int:
        try:
            api_instance = CustomFieldsApi(self.client)
            # Create a custom field.
            api_response = api_instance.create_custom_field(custom_field_create=CustomFieldCreate(**data))
            if not api_response.status:
                self.logger.log('Error creating custom field: ' + data['title'])
            else:
                self.logger.log('Custom field created: ' + data['title'])
                return api_response.result.id
        except ApiException as e:
            self.logger.log('Exception when calling CustomFieldsApi->create_custom_field: %s\n' % e, 'error')
            self.logger.log('Data being sent to API: %s' % json.dumps(data, indent=2, default=str), 'error')
        return 0

    def create_configuration_group(self, project_code, title):
        try:
            api_instance = ConfigurationsApi(self.client)
            # Create a custom field.
            api_response = api_instance.create_configuration_group(
                code=project_code,
                configuration_group_create=ConfigurationGroupCreate(title=title)
            )
            if not api_response.status:
                self.logger.log('Error creating configuration group: ' + title)
            else:
                self.logger.log('Configuration group created: ' + title)
                return api_response.result.id
        except ApiException as e:
            self.logger.log('Exception when calling CustomFieldsApi->create_configuration_group: %s\n' % e, 'error')
        return 0

    def create_configuration(self, project_code, title, group_id):
        try:
            api_instance = ConfigurationsApi(self.client)
            # Create a custom field.
            api_response = api_instance.create_configuration(
                code=project_code,
                configuration_create=ConfigurationCreate(title=title, group_id=group_id)
            )
            if not api_response.status:
                self.logger.log('Error creating configuration: ' + title)
            else:
                self.logger.log('Configuration created: ' + title)
                return api_response.result.id
        except ApiException as e:
            self.logger.log('Exception when calling CustomFieldsApi->create_configuration: %s\n' % e, 'error')
        return 0

    def get_system_fields(self):
        try:
            api_instance = SystemFieldsApi(self.client)
            # Get all system fields.
            api_response = api_instance.get_system_fields()
            if api_response.status and api_response.result:
                return api_response.result
        except ApiException as e:
            self.logger.log("Exception when calling SystemFieldsApi->get_system_fields: %s\n" % e, 'error')

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
                else:
                    # If no project_ids specified but field is not global, make it global as fallback
                    data['is_enabled_for_all_projects'] = True
                    self.logger.log(f'[Qase] Field {field["label"]} has no project_ids, making it global as fallback')
            
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
        for item in items:
            if item == '':
                continue
            key, value = item.split(delimiter)  # split each item into a key and a value
            result[key] = value
        return result

    def get_projects(self, limit=100, offset=0):
        try:
            api_instance = ProjectsApi(self.client)
            # Get all projects.
            api_response = api_instance.get_projects(limit, offset)
            if api_response.status and api_response.result:
                return api_response.result
        except ApiException as e:
            self.logger.log("Exception when calling ProjectsApi->get_projects: %s\n" % e, 'error')

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
            },
            'access': 'all'
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
                self.logger.log(f'Project with the same code already exists: {code}. Using existing project.')
                return True

            self.logger.log('Exception when calling ProjectsApi->create_project: %s\n' % e, 'error')
            self.logger.log('Data being sent to API: %s' % json.dumps(data, indent=2, default=str), 'error')
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
            # Create a new test cases.
            api_response = api_instance.bulk(code, TestCasebulk(cases=cases))
            return api_response.status
        except ApiException as e:
            self.logger.log("Exception when calling CasesApi->bulk: %s\n" % e)
            self.logger.log(f"Request payload: {cases}")
        return False

    def create_run(self, run: list, project_code: str, cases: list = [], milestone_id = None):
        api_instance = RunsApi(self.client)

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
            data['end_time'] = datetime.fromtimestamp(run['completed_on']).strftime('%Y-%m-%d %H:%M:%S')

        if milestone_id:
            data['milestone_id'] = milestone_id

        if len(cases) > 0:
            data['cases'] = cases

        try:
            response = api_instance.create_run(code=project_code, run_create=RunCreate(**data))
            return response.result.id
        except Exception as e:
            self.logger.log(f'Exception when calling RunsApi->create_run: {e}', 'error')
            self.logger.log('Data being sent to API: %s' % json.dumps(data, indent=2, default=str), 'error')

    def complete_run(self, project_code, run_id):
        api_instance = RunsApi(self.client)
        try:
            api_instance.complete_run(code=project_code, id=run_id)
        except Exception as e:
            self.logger.log(f'Exception when calling RunsApi->complete_run: {e}', 'error')

    def send_bulk_results(self, tr_run, results, qase_run_id, qase_code, mappings, cases_map):
        res = []

        if results:
            for result in results:
                if result['status_id'] != 3:

                    elapsed = 0
                    if 'elapsed' in result and result['elapsed']:
                        if type(result['elapsed']) is str:
                            elapsed = self.convert_to_seconds(result['elapsed'])
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
                            "comment": format_links_as_markdown(str(result['comment']))
                        }

                        if 'attachments' in result and len(result['attachments']) > 0:
                            data['attachments'] = result['attachments']

                        if start_time:
                            data['start_time'] = start_time

                        #if (result['defects']):
                            #self.defects.append({"case_id": result["case_id"],"defects": result['defects'],"run_id": qase_run_id})

                        # if result['created_by']:
                        #     data['author_id'] = mappings.get_user_id(result['created_by'])

                        if 'custom_step_results' in result and result['custom_step_results']:
                            data['steps'] = self.prepare_result_steps(result['custom_step_results'], mappings.result_statuses)

                        res.append(data)

            if len(res) > 0:
                api_results = ResultsApi(self.client)
                self.logger.log(f'Sending {len(res)} results to Qase')
                try:
                    api_results.create_result_bulk(
                        code=qase_code,
                        id=int(qase_run_id),
                        result_create_bulk=ResultCreateBulk(
                            results=res
                        )
                    )
                    self.logger.log(f'{len(res)} results sent to Qase')
                except Exception as e:
                    self.logger.log(f'Exception when calling ResultsApi->create_result_bulk: {e}', 'error')
                    self.logger.log('Data being sent to API: %s' % json.dumps(res, indent=2, default=str), 'error')

    def send_bulk_results_v2(self, tr_run, results, qase_run_id, qase_code, mappings, cases_map):
        """
        Send bulk results using Qase API v2
        
        This method uses the new qase-api-v2-client package and provides
        improved functionality for sending test results to Qase.
        
        Args:
            tr_run: TestRail run data
            results: List of test results from TestRail
            qase_run_id: Qase run ID
            qase_code: Qase project code
            mappings: Status mappings
            cases_map: Mapping of TestRail case IDs to Qase case IDs
        """
        res = []

        if results:
            for result in results:
                if result['status_id'] != 3:  # Skip untested status

                    elapsed = 0
                    if 'elapsed' in result and result['elapsed']:
                        if type(result['elapsed']) is str:
                            elapsed = self.convert_to_seconds(result['elapsed'])
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
                        
                        # Create ResultExecution object
                        execution = ResultExecution(
                            status=status,
                            duration=elapsed * 1000,  # converting to milliseconds
                            start_time=start_time,
                            end_time=start_time + elapsed if start_time else None
                        )

                        # Create ResultCreate object
                        result_data = ResultCreateV2(
                            title=f"Test result for case {result['test_id']}",  # You might want to get actual case title
                            testops_id=cases_map[result['test_id']],
                            execution=execution,
                            message=format_links_as_markdown(str(result['comment'])) if result.get('comment') else None
                        )

                        # Handle attachments
                        if 'attachments' in result and len(result['attachments']) > 0:
                            result_data.attachments = result['attachments']

                        # Handle custom step results
                        if 'custom_step_results' in result and result['custom_step_results']:
                            result_data.steps = self.prepare_result_steps_v2(result['custom_step_results'], mappings.result_statuses)

                        res.append(result_data)

            if len(res) > 0:
                api_results = ResultsApiV2(self.client_v2)
                self.logger.log(f'Model: {json.dumps(res, indent=2, default=str)}')
                self.logger.log(f'Sending {len(res)} results to Qase using API v2')
                try:
                    # Create bulk request
                    bulk_request = CreateResultsRequestV2(results=res)
                    
                    api_results.create_results_v2(
                        project_code=qase_code,
                        run_id=int(qase_run_id),
                        create_results_request_v2=bulk_request
                    )
                    self.logger.log(f'{len(res)} results sent to Qase using API v2')
                except Exception as e:
                    self.logger.log(f'Exception when calling ResultsApiV2->create_results_v2: {e}', 'error')
                    self.logger.log('Data being sent to API: %s' % json.dumps([r.to_dict() for r in res], indent=2, default=str), 'error')

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
            self.logger.log(f'Exception when preparing result steps: {e}', 'error')

        return data

    def prepare_result_steps_v2(self, steps, status_map) -> list:
        """
        Prepare result steps for API v2 using new ResultStep model
        """
        result_steps = []
        try:
            for step in steps:
                status_str = status_map.get(str(step.get('status_id')), 'skipped')
                
                # Map status to ResultStepStatus enum
                status_mapping = {
                    'passed': ResultStepStatus.PASSED,
                    'failed': ResultStepStatus.FAILED,
                    'blocked': ResultStepStatus.BLOCKED,
                    'skipped': ResultStepStatus.SKIPPED
                }
                step_status = status_mapping.get(status_str, ResultStepStatus.SKIPPED)

                # Create step execution
                step_execution = ResultStepExecution(
                    status=step_status,
                    comment=step.get('actual', '').strip() if step.get('actual') else None
                )

                # Create step data (action and expected result)
                step_data = ResultStepData(
                    action=step.get('content', 'No action').strip() if step.get('content') else 'No action',
                    expected_result=step.get('expected', '').strip() if step.get('expected') else None
                )

                # Create ResultStep
                result_step = ResultStep(
                    data=step_data,
                    execution=step_execution
                )

                result_steps.append(result_step)
        except Exception as e:
            self.logger.log(f'Exception when preparing result steps v2: {e}', 'error')

        return result_steps

    def convert_to_seconds(self, time_str: str) -> int:
        total_seconds = 0

        try:
            components = time_str.split()
            for component in components:
                if component.endswith('day'):
                    total_seconds += int(component[:-3]) * 86400  # 60 seconds * 60 minutes * 24 hours
                elif component.endswith('hr'):
                    total_seconds += int(component[:-2]) * 3600  # 60 seconds * 60 minutes
                elif component.endswith('min'):
                    total_seconds += int(component[:-3]) * 60
                elif component.endswith('sec'):
                    total_seconds += int(component[:-3])
        except Exception as e:
            self.logger.log(f'Exception when converting time string \'{time_str}\': {e}', 'warning')

        return total_seconds

    def upload_attachment(self, code, attachment_data):
        api_attachments = AttachmentsApi(self.client)
        
        # Extract filename and size from attachment_data (tuple: (filename, content))
        filename = "unknown"
        file_size = 0
        if isinstance(attachment_data, tuple) and len(attachment_data) >= 2:
            filename = attachment_data[0] if attachment_data[0] else "unknown"
            content = attachment_data[1]
            if content:
                file_size = len(content) if isinstance(content, bytes) else len(str(content))
        
        try:
            response = api_attachments.upload_attachment(
                    code, file=[attachment_data],
                )

            if response.status:
                return response.result[0].to_dict()
        except ApiException as e:
            # Check if it's a 413 error (Request Entity Too Large)
            status_code = None
            if hasattr(e, 'status'):
                status_code = e.status
            elif hasattr(e, 'status_code'):
                status_code = e.status_code
            else:
                # Try to extract status code from string representation
                # Format: "(413)\nReason: Request Entity Too Large"
                error_str = str(e)
                if '(413)' in error_str:
                    status_code = 413
            
            if status_code == 413:
                file_size_mb = file_size / (1024 * 1024) if file_size > 0 else 0
                self.logger.log(f'[{code}][Attachments] '
                    f'Exception when calling AttachmentsApi->upload_attachment: (413) Request Entity Too Large. '
                    f'File: {filename}, Size: {file_size} bytes ({file_size_mb:.2f} MB)',
                    'warning'
                )
            else:
                self.logger.log(f'Exception when calling AttachmentsApi->upload_attachment: {e}', 'warning')
        except Exception as e:
            # For other exceptions, also log file details if available
            file_size_mb = file_size / (1024 * 1024) if file_size > 0 else 0
            self.logger.log(f'[{code}][Attachments] '
                f'Exception when calling AttachmentsApi->upload_attachment: {e}. '
                f'File: {filename}, Size: {file_size} bytes ({file_size_mb:.2f} MB)',
                'warning'
            )
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
            action = step['content'].strip() if 'content' in step and type(step['content']) is str else 'No action'

            if action == '':
                action = 'No action'
            inner_steps.append(
                SharedStepContentCreate(
                    action=action,
                    expected_result=step['expected']
                )
            )

        api_instance = SharedStepsApi(self.client)
        api_response = api_instance.create_shared_step(project_code, SharedStepCreate(title=title, steps=inner_steps))
        return api_response.result.hash

    def check_field_update_needed(self, field, existing_field, mappings) -> tuple[bool, dict]:
        """
        Check if a field needs to be updated by comparing TestRail configuration with existing Qase field.
        Returns (needs_update, update_data).
        """
        needs_update = False
        update_data = {}
        
        # Check for missing values (for dropdown/multiselect fields)
        if field['type_id'] in (6, 12) and field.get('qase_values'):
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
            if missing_values:
                needs_update = True
                update_data['missing_values'] = list(missing_values)
                self.logger.log(f'[Qase] Field {field["label"]} missing values: {missing_values}')
        
        # Check if field needs qase_values mapping update
        if field['type_id'] in (6, 12) and not field.get('qase_values'):
            # Field exists but doesn't have qase_values mapping
            needs_update = True
            update_data['needs_mapping_update'] = True
            self.logger.log(f'[Qase] Field {field["label"]} needs qase_values mapping update')
        
        # Check for missing project codes
        if hasattr(existing_field, 'is_enabled_for_all_projects') and not existing_field.is_enabled_for_all_projects:
            existing_projects = set()
            if hasattr(existing_field, 'projects_codes') and existing_field.projects_codes:
                existing_projects = set(existing_field.projects_codes)
            
            expected_projects = set()
            
            if field.get('configs') and len(field['configs']) > 0:
                config = field['configs'][0]
                if not config.get('context', {}).get('is_global', False):
                    if config['context'].get('project_ids'):
                        for project_id in config['context']['project_ids']:
                            if project_id in mappings.project_map:
                                expected_projects.add(mappings.project_map[project_id])
            
            missing_projects = expected_projects - existing_projects
            if missing_projects:
                needs_update = True
                update_data['missing_projects'] = list(missing_projects)
                self.logger.log(f'[Qase] Field {field["label"]} missing projects: {missing_projects}')
        
        return needs_update, update_data

    def update_custom_field(self, field_id: int, update_data: dict) -> bool:
        """
        Update an existing custom field in Qase.
        """
        try:
            # Get the existing field first
            existing_field = self.get_custom_field(field_id)
            if not existing_field:
                self.logger.log(f'[Qase] Failed to get existing field {field_id} for update', 'error')
                return False
            
            # Prepare update payload
            update_payload = {}
            
            # Always include required fields
            if hasattr(existing_field, 'title'):
                update_payload['title'] = existing_field.title
            if hasattr(existing_field, 'type'):
                update_payload['type'] = existing_field.type
            if hasattr(existing_field, 'is_enabled_for_all_projects'):
                update_payload['is_enabled_for_all_projects'] = existing_field.is_enabled_for_all_projects
            
            # Always include value field (required by Qase API)
            if hasattr(existing_field, 'value') and existing_field.value:
                # Handle different types of value field
                if isinstance(existing_field.value, str):
                    # If value is a string, try to parse it as JSON
                    try:
                        import json
                        parsed_value = json.loads(existing_field.value)
                        if isinstance(parsed_value, list):
                            update_payload['value'] = parsed_value
                        else:
                            update_payload['value'] = []
                            self.logger.log(f'[Qase] Warning: Parsed value is not a list for field {field_id}')
                    except (json.JSONDecodeError, ValueError):
                        # If parsing fails, set empty list
                        update_payload['value'] = []
                        self.logger.log(f'[Qase] Warning: Failed to parse value string for field {field_id}, setting empty list')
                elif isinstance(existing_field.value, list):
                    update_payload['value'] = existing_field.value
                else:
                    update_payload['value'] = []
                    self.logger.log(f'[Qase] Warning: Unexpected value type {type(existing_field.value)} for field {field_id}, setting empty list')
            else:
                update_payload['value'] = []
            
            # Always include existing projects_codes to preserve field-project associations
            if hasattr(existing_field, 'projects_codes') and existing_field.projects_codes:
                update_payload['projects_codes'] = existing_field.projects_codes
            
            # Handle missing values
            if 'missing_values' in update_data:
                # Get existing values
                existing_values = []
                if hasattr(existing_field, 'value') and existing_field.value:
                    existing_values = existing_field.value
                
                # Add new values
                next_id = len(existing_values) + 1
                for value_title in update_data['missing_values']:
                    # Check if value already exists to avoid duplicates
                    existing_value_titles = {v.title for v in existing_values}
                    if value_title not in existing_value_titles:
                        existing_values.append({
                            'id': next_id,
                            'title': value_title
                        })
                        next_id += 1
                        self.logger.log(f'[Qase] Adding value "{value_title}" to field {field_id}')
                    else:
                        self.logger.log(f'[Qase] Value "{value_title}" already exists in field {field_id}')
                
                update_payload['value'] = existing_values
            
            # Handle mapping update
            if 'needs_mapping_update' in update_data:
                # This is a special case - we need to update the field's qase_values mapping
                # For now, we'll just log this and handle it in the calling code
                self.logger.log(f'[Qase] Field {field_id} needs mapping update - this should be handled by the calling code')
            
            # Handle missing projects
            if 'missing_projects' in update_data:
                existing_projects = getattr(existing_field, 'projects_codes', []) or []
                new_projects = existing_projects + update_data['missing_projects']
                update_payload['projects_codes'] = new_projects
                self.logger.log(f'[Qase] Adding projects {update_data["missing_projects"]} to field {field_id}')
            
            # If no updates needed, return success
            if not update_payload:
                self.logger.log(f'[Qase] No updates needed for field {field_id}')
                return True
            
            # Call the API to update the field
            api_instance = CustomFieldsApi(self.client)
            api_response = api_instance.update_custom_field(field_id, update_payload)
            
            if api_response.status:
                self.logger.log(f'[Qase] Successfully updated field {field_id}')
                return True
            else:
                self.logger.log(f'[Qase] Failed to update field {field_id}: {api_response.error}', 'error')
                return False
                
        except ApiException as e:
            self.logger.log(f'[Qase] Exception when updating field {field_id}: {e}', 'error')
            return False
        except Exception as e:
            self.logger.log(f'[Qase] Unexpected error when updating field {field_id}: {e}', 'error')
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
