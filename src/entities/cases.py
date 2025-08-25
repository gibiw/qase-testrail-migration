import asyncio
import re

from ..service import QaseService, TestrailService
from ..support import Logger, Mappings, ConfigManager as Config, Pools

from qaseio.models import TestStepCreate, TestCasebulkCasesInner
from .attachments import Attachments

from typing import List, Optional, Union

from urllib.parse import quote
from datetime import datetime
import json


class Cases:
    def __init__(
            self,
            qase_service: QaseService,
            testrail_service: TestrailService,
            logger: Logger,
            mappings: Mappings,
            config: Config,
            pools: Pools,
    ):
        self.qase = qase_service
        self.testrail = testrail_service
        self.config = config
        self.logger = logger
        self.mappings = mappings
        self.pools = pools
        self.attachments = Attachments(
            self.qase, self.testrail, self.logger, self.mappings, self.config, self.pools)
        self.total = 0
        self.logger.divider()

        self.project = None

    def import_cases(self, project: dict):
        return asyncio.run(self.import_cases_async(project))

    async def import_cases_async(self, project: dict):
        self.project = project

        async with asyncio.TaskGroup() as tg:
            if self.project['suite_mode'] == 3:
                suites = await self.pools.tr(self.testrail.get_suites, self.project['testrail_id'])
                for suite in suites:
                    tg.create_task(self.import_cases_for_suite(suite['id']))
            else:
                # Assuming None is a valid suite_id when suite_mode is not 3
                tg.create_task(self.import_cases_for_suite(None))

    async def import_cases_for_suite(self, suite_id):
        await self.process_cases(suite_id, 0, 0)

    async def process_cases(self, suite_id: int, offset: int, limit: int):
        try:
            if suite_id is None:
                suite_id = 0
            # Remove offset/limit since get_cases already handles pagination internally
            cases = await self.pools.tr(self.testrail.get_cases, self.project['testrail_id'], suite_id)
            self.mappings.stats.add_entity_count(
                self.project['code'], 'cases', 'testrail', len(cases))
            if cases:
                self.logger.print_status(
                    '['+self.project['code']+'] Importing test cases', self.total, self.total+len(cases), 1)
                self.logger.log(
                    f'[{self.project["code"]}][Tests] Importing {len(cases)} cases for suite {suite_id}')
                data = await self._prepare_cases(cases)
                if data:
                    self.logger.log(
                        f'[{self.project["code"]}][Tests] Sending {len(data)} cases for suite {suite_id}')
                    status = await self.pools.qs(self.qase.create_cases, self.project['code'], data)
                    if status:
                        self.mappings.stats.add_entity_count(
                            self.project['code'], 'cases', 'qase', len(cases))
                self.total = self.total + len(cases)
                self.logger.print_status(
                    '['+self.project['code']+'] Importing test cases', self.total, self.total, 1)
            return len(cases)
        except Exception as e:
            self.logger.log(
                f"[{self.project['code']}][Tests] Error processing cases for suite {suite_id}: {e}", 'error')
            return 0

    async def _prepare_cases(self, cases: List) -> List:
        result = []
        tasks = []
        
        # Create all tasks
        for case in cases:
            task = self._prepare_case(case, result)
            tasks.append(task)
        
        # Wait for all tasks to complete
        await asyncio.gather(*tasks)
        
        return result

    async def _prepare_case(self, case, result):
        data = {
            'id': int(case['id']),
            'title': case['title'],
            'created_at': str(datetime.fromtimestamp(case['created_on'])),
            'updated_at': str(datetime.fromtimestamp(case['updated_on'])),
            'author_id': self.mappings.get_user_id(case['created_by']),
            'steps': [],
            'attachments': [],
            'is_flaky': 0,
            'custom_field': {},
        }

        # import custom fields
        data = self._import_custom_fields_for_case(case=case, data=data)
        data = await self._get_attachments_for_case(case=case, data=data)

        data = self._set_priority(case=case, data=data)
        data = self._set_type(case=case, data=data)
        data = self._set_status(case=case, data=data)
        data = self._set_suite(case=case, data=data)
        data = self._set_refs(case=case, data=data)
        data = self._set_milestone(
            case=case, data=data, code=self.project['code'])

        result.append(
            TestCasebulkCasesInner(
                **data
            )
        )

    # Done
    def _set_refs(self, case: dict, data: dict) -> dict:
        if not (self.mappings.refs_id and case.get('refs') and self.config.get('tests.refs.enable')):
            return data

        refs = [ref.strip() for ref in case['refs'].split(',')]

        processed_refs = []
        for ref in refs:
            if ref.startswith('http'):
                processed_ref = f"[{ref}]({ref})"
            else:
                # Use Jira browse path for non-HTTP refs
                processed_ref = f"[{ref}](https://blueowl.atlassian.net/browse/{ref})"
            processed_ref = self.__format_links_as_markdown(processed_ref)
            processed_refs.append(processed_ref)

        data['custom_field'][str(self.mappings.refs_id)
                             ] = '\n'.join(processed_refs)

        return data

    @staticmethod
    def _get_ref(ref: str, url: str) -> str:
        if ref.startswith('http'):
            return quote(ref, safe="/:")
        return quote(f"{url}/{ref}", safe="/:")

    async def _get_attachments_for_case(self, case: dict, data: dict) -> dict:
        self.logger.log(
            f'[{self.project["code"]}][Tests] Getting attachments for case {case["title"]}')
        try:
            attachments = await self.pools.tr(self.testrail.get_attachments_case, case['id'])
        except Exception as e:
            self.logger.log(
                f'[{self.project["code"]}][Tests] Failed to get attachments for case {case["title"]}: {e}', 'error')
            return data
        self.logger.log(
            f'[{self.project["code"]}][Tests] Found {len(attachments)} attachments for case {case["title"]}')
        for attachment in attachments:
            try:
                id = attachment['id']
                if 'data_id' in attachment:
                    id = attachment['data_id']
                if id in self.mappings.attachments_map:
                    data['attachments'].append(
                        self.mappings.attachments_map[id]['hash'])
            except Exception as e:
                self.logger.log(
                    f'[{self.project["code"]}][Tests] Failed to get attachment for case {case["title"]}: {e}', 'error')
        return data

    # Done
    def _import_custom_fields_for_case(self, case: dict, data: dict) -> dict:
        self.logger.log(f'[{self.project["code"]}][Tests] Starting custom fields import for case: {case.get("title", "Unknown")}')
        self.logger.log(f'[{self.project["code"]}][Tests] Available custom fields in mappings: {list(self.mappings.custom_fields.keys())}')
        
        for field_name in case:
            if field_name.startswith('custom_') and field_name[len('custom_'):] in self.mappings.custom_fields and case[field_name]:
                name = field_name[len('custom_'):]
                custom_field = self.mappings.custom_fields[name]
                self.logger.log(f'[{self.project["code"]}][Tests] Processing custom field: {field_name} -> {name}')
                self.logger.log(f'[{self.project["code"]}][Tests] Field value from TestRail: {case[field_name]}')
                self.logger.log(f'[{self.project["code"]}][Tests] Field type_id: {custom_field.get("type_id")}')
                
                # Importing step

                if custom_field['type_id'] in (6, 12):
                    # Importing dropdown and multiselect values
                    self.logger.log(f'[{self.project["code"]}][Tests] Field {name} is dropdown/multiselect (type_id: {custom_field["type_id"]})')
                    self.logger.log(f'[{self.project["code"]}][Tests] Field has tr_key_to_qase_id_by_project: {"tr_key_to_qase_id_by_project" in custom_field}')
                    if "tr_key_to_qase_id_by_project" in custom_field:
                        self.logger.log(f'[{self.project["code"]}][Tests] Available projects in mapping: {list(custom_field["tr_key_to_qase_id_by_project"].keys())}')
                        if self.project['testrail_id'] in custom_field['tr_key_to_qase_id_by_project']:
                            project_mapping = custom_field['tr_key_to_qase_id_by_project'][self.project['testrail_id']]
                            self.logger.log(f'[{self.project["code"]}][Tests] Project {self.project["testrail_id"]} mapping: {project_mapping}')
                    
                    value = self._validate_custom_field_values(
                        custom_field, case[field_name])
                    if value:
                        if type(value) == str or type(value) == int:
                            self.logger.log(f'[{self.project["code"]}][Tests] Processing custom field "{custom_field["name"]}" with value: {value} (type: {type(value)})')
                            self.logger.log(f'[{self.project["code"]}][Tests] Custom field data: {custom_field}')
                            self.logger.log(f'[{self.project["code"]}][Tests] Project TestRail ID: {self.project["testrail_id"]}')
                            
                            # Use the project-specific mapping from TestRail key to Qase ID
                            if ('tr_key_to_qase_id_by_project' in custom_field and 
                                self.project['testrail_id'] in custom_field['tr_key_to_qase_id_by_project'] and
                                str(value) in custom_field['tr_key_to_qase_id_by_project'][self.project['testrail_id']]):
                                
                                qase_id = custom_field['tr_key_to_qase_id_by_project'][self.project['testrail_id']][str(value)]
                                data['custom_field'][str(custom_field['qase_id'])] = str(qase_id)
                                self.logger.log(f'[{self.project["code"]}][Tests] SUCCESS: Mapped TestRail value {value} to Qase ID {qase_id} for project {self.project["testrail_id"]}')
                            else:
                                # Log why the mapping failed
                                if 'tr_key_to_qase_id_by_project' not in custom_field:
                                    self.logger.log(f'[{self.project["code"]}][Tests] FAILED: No tr_key_to_qase_id_by_project in custom field')
                                elif self.project['testrail_id'] not in custom_field['tr_key_to_qase_id_by_project']:
                                    self.logger.log(f'[{self.project["code"]}][Tests] FAILED: Project {self.project["testrail_id"]} not found in tr_key_to_qase_id_by_project. Available projects: {list(custom_field["tr_key_to_qase_id_by_project"].keys())}')
                                elif str(value) not in custom_field['tr_key_to_qase_id_by_project'][self.project['testrail_id']]:
                                    available_values = list(custom_field['tr_key_to_qase_id_by_project'][self.project['testrail_id']].keys())
                                    self.logger.log(f'[{self.project["code"]}][Tests] FAILED: Value {value} not found in project {self.project["testrail_id"]}. Available values: {available_values}')
                                
                                # Fallback to old logic if mapping not available
                                fallback_id = str(int(value) + 1)
                                data['custom_field'][str(custom_field['qase_id'])] = fallback_id
                                self.logger.log(f'[{self.project["code"]}][Tests] Using fallback mapping for value {value} -> {fallback_id} in project {self.project["testrail_id"]}')
                        if type(value) == list:
                            self.logger.log(f'[{self.project["code"]}][Tests] Processing custom field "{custom_field["name"]}" with list value: {value}')
                            self.logger.log(f'[{self.project["code"]}][Tests] Custom field data: {custom_field}')
                            self.logger.log(f'[{self.project["code"]}][Tests] Project TestRail ID: {self.project["testrail_id"]}')
                            
                            # Handle list values
                            qase_ids = []
                            for v in value:
                                self.logger.log(f'[{self.project["code"]}][Tests] Processing list item: {v}')
                                
                                if ('tr_key_to_qase_id_by_project' in custom_field and 
                                    self.project['testrail_id'] in custom_field['tr_key_to_qase_id_by_project'] and
                                    str(v) in custom_field['tr_key_to_qase_id_by_project'][self.project['testrail_id']]):
                                    
                                    qase_id = custom_field['tr_key_to_qase_id_by_project'][self.project['testrail_id']][str(v)]
                                    qase_ids.append(str(qase_id))
                                    self.logger.log(f'[{self.project["code"]}][Tests] SUCCESS: Mapped TestRail value {v} to Qase ID {qase_id} for project {self.project["testrail_id"]}')
                                else:
                                    # Log why the mapping failed for this list item
                                    if 'tr_key_to_qase_id_by_project' not in custom_field:
                                        self.logger.log(f'[{self.project["code"]}][Tests] FAILED: No tr_key_to_qase_id_by_project in custom field for list item {v}')
                                    elif self.project['testrail_id'] not in custom_field['tr_key_to_qase_id_by_project']:
                                        self.logger.log(f'[{self.project["code"]}][Tests] FAILED: Project {self.project["testrail_id"]} not found in tr_key_to_qase_id_by_project for list item {v}. Available projects: {list(custom_field["tr_key_to_qase_id_by_project"].keys())}')
                                    elif str(v) not in custom_field['tr_key_to_qase_id_by_project'][self.project['testrail_id']]:
                                        available_values = list(custom_field['tr_key_to_qase_id_by_project'][self.project['testrail_id']].keys())
                                        self.logger.log(f'[{self.project["code"]}][Tests] FAILED: List item value {v} not found in project {self.project["testrail_id"]}. Available values: {available_values}')
                                    
                                    # Fallback to old logic
                                    fallback_id = str(int(v) + 1)
                                    qase_ids.append(fallback_id)
                                    self.logger.log(f'[{self.project["code"]}][Tests] Using fallback mapping for list item {v} -> {fallback_id} in project {self.project["testrail_id"]}')
                            
                            final_value = ','.join(qase_ids)
                            data['custom_field'][str(custom_field['qase_id'])] = final_value
                            self.logger.log(f'[{self.project["code"]}][Tests] Final list mapping result: {value} -> {final_value}')
                    else:
                        # Log when validation returns None for debugging
                        self.logger.log(
                            f'[{self.project["code"]}][Tests] Custom field {name} validation returned None for value: {case[field_name]}', 'warning')
                        # Log available options for debugging
                        if len(custom_field['configs']) > 0 and 'options' in custom_field['configs'][0]:
                            values = self.__split_values(custom_field['configs'][0]['options']['items'])
                            self.logger.log(
                                f'[{self.project["code"]}][Tests] Available options for {name}: {values}', 'info')
                else:
                    # Check if this is a URL field and handle accordingly
                    field_value = str(
                        self.attachments.check_and_replace_attachments(
                            case[field_name], self.project['code'])
                    )
                    
                    # Check if this custom field is a URL type in Qase
                    if self._is_url_field(custom_field['qase_id']):
                        # For URL fields, extract plain URL from markdown if needed
                        plain_url = self._extract_url_from_markdown(field_value)
                        data['custom_field'][str(custom_field['qase_id'])] = plain_url
                        self.logger.log(
                            f'[{self.project["code"]}][Tests] Custom field {name} (ID: {custom_field["qase_id"]}) - URL type: original={case[field_name]} -> processed={field_value} -> result={plain_url}', 'info')
                    else:
                        # For non-URL fields, apply markdown formatting
                        formatted_value = self.__format_links_as_markdown(field_value)
                        data['custom_field'][str(custom_field['qase_id'])] = formatted_value
                        self.logger.log(
                            f'[{self.project["code"]}][Tests] Custom field {name} (ID: {custom_field["qase_id"]}) - {custom_field["type_id"]} type: original={case[field_name]} -> processed={field_value} -> result={formatted_value}', 'info')
                        
            if field_name[len('custom_'):] in self.mappings.step_fields and case[field_name]:
                steps = []
                i = 1
                for step in case[field_name]:
                    action = self.attachments.check_and_replace_attachments(
                        step['content'], self.project['code'])
                    expected = self.attachments.check_and_replace_attachments(
                        step['expected'], self.project['code'])
                    input_data = self.attachments.check_and_replace_attachments(
                        step.get('additional_info', ''), self.project['code'])

                    action = action.strip()
                    expected = expected.strip()

                    if (action != '' or (action == '' and expected != '')):
                        if action == '' or action == ' ':
                            action = 'No action'
                        steps.append(
                            TestStepCreate(
                                action=self.__format_links_as_markdown(action),
                                expected_result=self.__format_links_as_markdown(
                                    expected),
                                data=self.__format_links_as_markdown(
                                    input_data),
                                position=i
                            )
                        )
                        i += 1
                    else:
                        self.logger.log(
                            f'[{self.project["code"]}][Tests] Case {case["title"]} has invalid step {step}', 'warning')
                data['steps'] = steps
        
        # Handle required custom fields that don't exist in TestRail data
        data = self._handle_required_custom_fields(data)
        
        self.logger.log(f'[{self.project["code"]}][Tests] Final custom fields result: {data.get("custom_field", {})}')
        self.logger.log(f'[{self.project["code"]}][Tests] Data before validation: {data}', 'info')

        # # Validate and fix any invalid custom field values
        # data = self._validate_and_fix_custom_field_values(data)

        # self.logger.log(f'[{self.project["code"]}][Tests] Data after validation: {data}', 'info')
        
        return data

    def _is_url_field(self, qase_field_id: int) -> bool:
        """Check if a custom field is a URL type in Qase"""
        try:
            qase_custom_fields = self.qase.get_case_custom_fields()
            if qase_custom_fields:
                for qase_field in qase_custom_fields:
                    if qase_field.id == qase_field_id:
                        return qase_field.type.lower() == 'url'
        except Exception as e:
            self.logger.log(
                f'[{self.project["code"]}][Tests] Error checking field type for ID {qase_field_id}: {e}', 'warning')
        return False

    def _extract_url_from_markdown(self, text: str) -> str:
        """Extract plain URL from markdown link format [text](url) or return original text if not markdown"""
        if not text:
            return text
            
        # Check if text is in markdown link format [text](url)
        import re
        markdown_link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        match = re.search(markdown_link_pattern, text)
        
        if match:
            # Extract the URL part from [text](url)
            url = match.group(2)
            self.logger.log(
                f'[{self.project["code"]}][Tests] Extracted URL from markdown: {text} -> {url}', 'info')
            return url
        else:
            # If not markdown format, check if it's already a plain URL
            url_pattern = r'^https?://[^\s]+$'
            if re.match(url_pattern, text.strip()):
                return text.strip()
            else:
                # If it's not a valid URL, return empty string to avoid validation errors
                self.logger.log(
                    f'[{self.project["code"]}][Tests] Invalid URL format, using empty string: {text}', 'warning')
                return ''

    def _handle_required_custom_fields(self, data: dict) -> dict:
        """Handle required custom fields that don't exist in TestRail data by providing default values"""
        # Get all Qase custom fields to check which ones are required
        try:
            qase_custom_fields = self.qase.get_case_custom_fields()
            if qase_custom_fields:
                for qase_field in qase_custom_fields:
                    # Check if this field is required and not already provided
                    if hasattr(qase_field, 'is_required') and qase_field.is_required:
                        field_id_str = str(qase_field.id)
                        if field_id_str not in data['custom_field']:
                            # Provide a default value based on field type
                            default_value = self._get_default_value_for_field(qase_field)
                            if default_value is not None:
                                data['custom_field'][field_id_str] = default_value
                                self.logger.log(
                                    f'[{self.project["code"]}][Tests] Providing default value for required custom field {qase_field.title} (ID: {qase_field.id}): {default_value}', 'info')
        except Exception as e:
            self.logger.log(
                f'[{self.project["code"]}][Tests] Error handling required custom fields: {e}', 'warning')
        
        return data

    def _validate_and_fix_custom_field_values(self, data: dict) -> dict:
        """Validate and fix any invalid custom field values before sending to Qase"""
        try:
            qase_custom_fields = self.qase.get_case_custom_fields()
            if qase_custom_fields:
                for qase_field in qase_custom_fields:
                    field_id_str = str(qase_field.id)
                    if field_id_str in data['custom_field']:
                        current_value = data['custom_field'][field_id_str]
                        
                        # For dropdown/select fields, validate the value
                        if qase_field.type.lower() in ['selectbox', 'radio', 'multiselect', 'checkbox']:
                            if hasattr(qase_field, 'value') and qase_field.value:
                                try:
                                    valid_options = json.loads(qase_field.value)
                                    valid_ids = [str(option['id']) for option in valid_options]
                                    
                                    # Check if current value is valid
                                    if isinstance(current_value, str):
                                        if current_value not in valid_ids:
                                            # Use first valid option as fallback
                                            if valid_ids:
                                                data['custom_field'][field_id_str] = valid_ids[0]
                                                self.logger.log(
                                                    f'[{self.project["code"]}][Tests] Fixed invalid value for custom field {qase_field.title} (ID: {qase_field.id}): {current_value} -> {valid_ids[0]}', 'info')
                                    elif isinstance(current_value, list):
                                        # For multiselect fields
                                        valid_values = [v for v in current_value if str(v) in valid_ids]
                                        if not valid_values and valid_ids:
                                            valid_values = [valid_ids[0]]
                                            self.logger.log(
                                                f'[{self.project["code"]}][Tests] Fixed invalid values for custom field {qase_field.title} (ID: {qase_field.id}): {current_value} -> {valid_values}', 'info')
                                        data['custom_field'][field_id_str] = valid_values
                                except Exception as e:
                                    self.logger.log(
                                        f'[{self.project["code"]}][Tests] Error validating custom field {qase_field.title}: {e}', 'warning')
                        if qase_field.type.lower() == 'url':
                            # Extract URL from markdown format [text](url) if present
                            extracted_url = self._extract_url_from_markdown(current_value)
                            if extracted_url:
                                data['custom_field'][field_id_str] = extracted_url
        except Exception as e:
            self.logger.log(
                f'[{self.project["code"]}][Tests] Error validating custom field values: {e}', 'warning')
        
        return data

    def _get_default_value_for_field(self, qase_field) -> str:
        """Get appropriate default value for a required custom field based on its type"""
        try:
            field_type = qase_field.type.lower()
            
            if field_type in ['text', 'textarea']:
                return 'Migrated from TestRail'
            elif field_type in ['number']:
                return '0'
            elif field_type in ['url']:
                return 'https://blueowl.atlassian.net/wiki/spaces/EN/pages/viewpage.action?pageId=1'
            elif field_type in ['email']:
                return 'migration@example.com'
            elif field_type in ['selectbox', 'radio']:
                # For select fields, try to use the first available option
                if hasattr(qase_field, 'value') and qase_field.value:
                    try:
                        values = json.loads(qase_field.value)
                        if values and len(values) > 0:
                            return str(values[0]['id'])
                    except:
                        pass
                return '1'  # Default to first option
            elif field_type in ['multiselect', 'checkbox']:
                # For multiselect fields, try to use the first available option
                if hasattr(qase_field, 'value') and qase_field.value:
                    try:
                        values = json.loads(qase_field.value)
                        if values and len(values) > 0:
                            return str(values[0]['id'])
                    except:
                        pass
                return '1'  # Default to first option
            else:
                return 'Migrated from TestRail'
        except Exception as e:
            self.logger.log(
                f'[{self.project["code"]}][Tests] Error getting default value for field {qase_field.title}: {e}', 'warning')
            return 'Migrated from TestRail'

    # Done. Method validates if custom field value exists (skip)
    def _validate_custom_field_values(self, custom_field: dict, value: Union[str, List]) -> Optional[Union[str, list]]:
        # Get project-specific values if available
        project_values = None
        if 'project_values' in custom_field and self.project['testrail_id'] in custom_field['project_values']:
            project_values = custom_field['project_values'][self.project['testrail_id']]
            self.logger.log(f'[{self.project["code"]}][Tests] Using project-specific values for field {custom_field["name"]} in project {self.project["testrail_id"]}')
        
        # Fallback to first config if no project-specific values
        if project_values is None and len(custom_field['configs']) > 0:
            if 'options' in custom_field['configs'][0] and 'items' in custom_field['configs'][0]['options']:
                project_values = self.__split_values(custom_field['configs'][0]['options']['items'])
                self.logger.log(f'[{self.project["code"]}][Tests] Using fallback values for field {custom_field["name"]} in project {self.project["testrail_id"]}')
        
        if project_values and len(project_values) > 0:
            # Create reverse mapping for better value matching
            value_to_key = {v.strip(): k for k, v in project_values.items()}
            
            if type(value) == str or type(value) == int:
                str_value = str(value).strip()
                
                # First try exact key match
                if str_value in project_values.keys():
                    return value
                
                # Then try value match (case-insensitive)
                if str_value.lower() in [v.lower() for v in project_values.values()]:
                    for k, v in project_values.items():
                        if v.lower() == str_value.lower():
                            return k
                
                # For multi-select fields, try to split and match individual values
                if ',' in str_value:
                    parts = [part.strip() for part in str_value.split(',')]
                    matched_parts = []
                    for part in parts:
                        if part in project_values.keys():
                            matched_parts.append(part)
                        elif part.lower() in [v.lower() for v in project_values.values()]:
                            for k, v in project_values.items():
                                if v.lower() == part.lower():
                                    matched_parts.append(k)
                                    break
                        else:
                            self.logger.log(
                                f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} has unmatched value "{part}" in "{str_value}" for project {self.project["testrail_id"]}', 'warning')
                    
                    if matched_parts:
                        return matched_parts
                
                # Log the issue but don't use fallback - preserve original value
                self.logger.log(
                    f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} has unmatched value "{str_value}" for project {self.project["testrail_id"]}, preserving original', 'warning')
                return value
                
            elif type(value) == list:
                filtered_values = []
                for item in value:
                    str_item = str(item).strip()
                    
                    # Try exact key match
                    if str_item in project_values.keys():
                        filtered_values.append(item)
                        continue
                    
                    # Try value match (case-insensitive)
                    if str_item.lower() in [v.lower() for v in project_values.values()]:
                        for k, v in project_values.items():
                            if v.lower() == str_item.lower():
                                filtered_values.append(k)
                                break
                        continue
                    
                    # For multi-select items, try to split and match
                    if ',' in str_item:
                        parts = [part.strip() for part in str_item.split(',')]
                        for part in parts:
                            if part in project_values.keys():
                                filtered_values.append(part)
                            elif part.lower() in [v.lower() for v in project_values.values()]:
                                for k, v in project_values.items():
                                    if v.lower() == part.lower():
                                        filtered_values.append(k)
                                        break
                            else:
                                self.logger.log(
                                    f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} has unmatched list item "{part}" in "{str_item}" for project {self.project["testrail_id"]}', 'warning')
                    else:
                        self.logger.log(
                            f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} has unmatched list value "{str_item}" for project {self.project["testrail_id"]}', 'warning')
                
                if filtered_values:
                    return filtered_values
                else:
                    # Log but preserve original value instead of using fallback
                    self.logger.log(
                        f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} has no matched values from "{value}" for project {self.project["testrail_id"]}, preserving original', 'warning')
                    return value
            
            return value
        return value  # Return the original value instead of None

    def __split_values(self, string: str, delimiter: str = ',') -> dict:
        items = string.split('\n')  # split items into a list
        result = {}
        seen_titles = set()  # Track seen titles to avoid duplicates

        for item in items:
            if item == '' or item is None:
                continue
            # split each item into a key and a value
            key, value = item.split(delimiter)
            # Trim the title and skip empty titles
            trimmed_value = value.strip()
            if trimmed_value and trimmed_value not in seen_titles:
                result[key] = trimmed_value
                seen_titles.add(trimmed_value)
        return result

    # Done
    def _set_priority(self, case: dict, data: dict) -> dict:
        data['priority'] = self.mappings.priorities[case['priority_id']
                                                    ] if case['priority_id'] in self.mappings.priorities else 1
        return data

    # Done
    def _set_type(self, case: dict, data: dict) -> dict:
        data['type'] = self.mappings.types[case['type_id']
                                           ] if case['type_id'] in self.mappings.types else 1
        return data

    def _set_status(self, case: dict, data: dict) -> dict:
        # Not used yet, as testrail doesn't return case statuses
        return data
        data['status'] = self.mappings.case_statuses[case['status_id']
                                                     ] if case['status_id'] in self.mappings.case_statuses else 1
        return data

    # Done
    def _set_suite(self, case: dict, data: dict) -> dict:
        suite_id = self._get_suite_id(section_id=case['section_id'])
        if (suite_id):
            data['suite_id'] = suite_id
        return data

    # Done
    def _get_suite_id(self, section_id: Optional[int] = None) -> int:
        if (section_id and section_id in self.mappings.suites[self.project['code']]):
            return self.mappings.suites[self.project['code']][section_id]
        return None

    def _set_milestone(self, case: dict, data: dict, code: str) -> dict:
        if case['milestone_id'] and code in self.mappings.milestones and case['milestone_id'] in \
                self.mappings.milestones[code]:
            data['milestone_id'] = self.mappings.milestones[code][case['milestone_id']]
        return data

    @staticmethod
    def __format_links_as_markdown(text):
        if text is None:
            return None

        # Don't process if text is already empty
        if not text.strip():
            return text

        # Check if text already contains markdown links to avoid double-processing
        if re.search(r'\[.*?\]\(.*?\)', text):
            # Text already contains markdown links, return as-is
            return text

        # Only convert plain URLs to markdown format if they're not already in markdown
        # Use a more precise regex that doesn't match URLs already in markdown
        url_pattern = re.compile(r'(?<!\]\()(?<!\])\b(http[s]?://[^\s\)]+)')
        formatted_text = url_pattern.sub(r'[\1](\1)', text)

        return formatted_text
