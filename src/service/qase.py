from ..support import ConfigManager, Logger

import certifi
import json
import time

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
        if not field['configs'] or field['configs'][0]['context']['is_global']:
            data['is_enabled_for_all_projects'] = True
        else:
            data['is_enabled_for_all_projects'] = False
            if field['configs'][0]['context']['project_ids']:
                data['projects_codes'] = []
                for config in field['configs']:
                    for id in config['context']['project_ids']:
                        if id in mappings.project_map:
                            data['projects_codes'].append(
                                mappings.project_map[id])

        if self.__get_default_value(field):
            data['default_value'] = self.__get_default_value(field)
        if field['type_id'] == 12 or field['type_id'] == 6:
            if len(field['configs']) > 0:
                values = self.__split_values(
                    field['configs'][0]['options']['items'])
                field['qase_values'] = {}
                for key, value in values.items():
                    data['value'].append(
                        CustomFieldCreateValueInner(
                            # hack as in testrail ids can start from 0
                            id=int(key)+1,
                            title=value,
                        ),
                    )
                    field['qase_values'][int(key)+1] = value
            else:
                self.logger.log('Error creating custom field: ' +
                                field['label'] + '. No options found', 'warning')
        return data

    @staticmethod
    def __get_default_value(field):
        if 'configs' in field:
            if len(field['configs']) > 0:
                if 'options' in field['configs'][0]:
                    if 'default_value' in field['configs'][0]['options']:
                        return field['configs'][0]['options']['default_value']
        return None

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

        # Add delay to avoid API rate limiting
        self.logger.log(f"Adding 2 second delay before creating run '{run['name']}' to avoid rate limiting...")
        time.sleep(2)

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
                
                # Add delay to avoid API rate limiting
                self.logger.log('Adding 2 second delay before API call to avoid rate limiting...')
                time.sleep(2)
                
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
