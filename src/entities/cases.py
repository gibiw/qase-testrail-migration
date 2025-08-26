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
        # Special logging for field 133
        if 'custom_133' in case:
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 found in case {case["title"]}')
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 value: {case["custom_133"]}')
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 value type: {type(case["custom_133"])}')
        
        for field_name in case:
            if field_name.startswith('custom_'):
                normalized_name = self.__normalize_custom_field_name(field_name[len('custom_'):])
                
                # Special logging for field 133
                if field_name == 'custom_133':
                    self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Processing field 133 - normalized_name: {normalized_name}')
                    self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - project_specific_key: {normalized_name}_{self.project["code"]}')
                    self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - in custom_fields: {normalized_name}_{self.project["code"] in self.mappings.custom_fields}')
                    if f"{normalized_name}_{self.project['code']}" in self.mappings.custom_fields:
                        custom_field = self.mappings.custom_fields[f"{normalized_name}_{self.project['code']}"]
                        self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - custom_field: {custom_field}')
                
                # Look for project-specific field first
                project_specific_key = f"{normalized_name}_{self.project['code']}"
                if project_specific_key in self.mappings.custom_fields and case[field_name]:
                    custom_field = self.mappings.custom_fields[project_specific_key]
                    self.logger.log(f'[{self.project["code"]}][Tests] Using project-specific field {project_specific_key} for case {case["title"]} with value: {case[field_name]}')

                    # Importing step

                    if custom_field['type_id'] in (6, 12):
                        # Importing dropdown and multiselect values
                        value = self._validate_custom_field_values(custom_field, case[field_name])
                        if value:
                            if type(value) == str or type(value) == int:
                                # For single values, we need to map TestRail value to Qase value
                                testrail_key = str(value)
                                qase_value = None
                                
                                # Try to find mapping in tr_key_to_qase_id first
                                if custom_field.get('tr_key_to_qase_id') and testrail_key in custom_field['tr_key_to_qase_id']:
                                    qase_value = custom_field['tr_key_to_qase_id'][testrail_key]
                                    self.logger.log(f'[{self.project["code"]}][Tests] Using tr_key_to_qase_id mapping for field {custom_field["name"]}: {testrail_key} -> {qase_value}')
                                elif custom_field.get('qase_values') and testrail_key in custom_field['qase_values']:
                                    # Fallback to old logic if tr_key_to_qase_id not available
                                    qase_value = custom_field['qase_values'][testrail_key]
                                    self.logger.log(f'[{self.project["code"]}][Tests] Using qase_values fallback for field {custom_field["name"]}: {testrail_key} -> {qase_value}')
                                
                                if qase_value is None:
                                    # If no mapping found, log warning and skip this field
                                    self.logger.log(f'[{self.project["code"]}][Tests] Warning: No Qase mapping found for TestRail value {testrail_key} in field {custom_field["name"]}', 'warning')
                                    continue
                                
                                data['custom_field'][str(custom_field['qase_id'])] = str(qase_value)
                                self.logger.log(f'[{self.project["code"]}][Tests] Set field {custom_field["name"]} to value: {str(qase_value)}')

                            elif type(value) == list:
                                # Multiple values - handle based on field type
                                if custom_field['type_id'] == 12:  # multiselect
                                    # For multiselect, pass comma-separated string
                                    if not custom_field.get('project_id'):
                                        # For global fields, use validated values directly
                                        validated_values = self._validate_custom_field_values(custom_field, value)

                                        if validated_values:
                                            # Convert validated TestRail values to Qase IDs
                                            qase_values = []
                                            for v in validated_values:
                                                # Find the corresponding Qase ID for this TestRail value
                                                testrail_key = str(v)
                                                if custom_field.get('tr_key_to_qase_id') and testrail_key in custom_field['tr_key_to_qase_id']:
                                                    qase_id = custom_field['tr_key_to_qase_id'][testrail_key]
                                                    qase_values.append(str(qase_id))
                                                elif custom_field.get('qase_values') and testrail_key in custom_field['qase_values']:
                                                    # Fallback to old logic if tr_key_to_qase_id not available
                                                    qase_id = custom_field['qase_values'][testrail_key]
                                                    qase_values.append(str(qase_id))
                                                else:
                                                    self.logger.log(f'[{self.project["code"]}][Tests] Warning: TestRail value {v} not found in mapping for field {custom_field["name"]}', 'warning')
                                            
                                            if qase_values:
                                                data['custom_field'][str(custom_field['qase_id'])] = ','.join(qase_values)
                                                self.logger.log(f'[{self.project["code"]}][Tests] Set global multiselect field {custom_field["name"]} to values: {",".join(qase_values)}')
                                            else:
                                                self.logger.log(f'[{self.project["code"]}][Tests] No valid Qase IDs found for field {custom_field["name"]}', 'warning')
                                        else:
                                            self.logger.log(f'[{self.project["code"]}][Tests] Global field {custom_field["name"]} validation failed for value: {value}')
                                    else:
                                        # For project-specific fields, use the old logic
                                        qase_values = [str(int(v) + 1) for v in value]
                                        data['custom_field'][str(custom_field['qase_id'])] = ','.join(qase_values)
                                        self.logger.log(f'[{self.project["code"]}][Tests] Set project-specific multiselect field {custom_field["name"]} to values: {",".join(qase_values)}')
                                else:  # single select (type_id = 6)
                                    # For single select, take first value only
                                    data['custom_field'][str(custom_field['qase_id'])] = str(int(value[0]) + 1)
                                    self.logger.log(f'[{self.project["code"]}][Tests] Set single select field {custom_field["name"]} to value: {str(int(value[0]) + 1)}')

                        else:
                            self.logger.log(f'[{self.project["code"]}][Tests] Field {custom_field["name"]} validation failed for value: {case[field_name]}')

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
                                f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} (ID: {custom_field["qase_id"]}) - URL type: original={case[field_name]} -> processed={field_value} -> result={plain_url}', 'info')
                        else:
                            # For non-URL fields, apply markdown formatting
                            formatted_value = self.__format_links_as_markdown(field_value)
                            data['custom_field'][str(custom_field['qase_id'])] = formatted_value
                            self.logger.log(
                                f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} (ID: {custom_field["qase_id"]}) - {custom_field["type_id"]} type: original={case[field_name]} -> processed={field_value} -> result={formatted_value}', 'info')

                            
                # Fallback to original field name for backward compatibility
                elif normalized_name in self.mappings.custom_fields and case[field_name]:
                    custom_field = self.mappings.custom_fields[normalized_name]
                    self.logger.log(f'[{self.project["code"]}][Tests] Using global field {normalized_name} for case {case["title"]} with value: {case[field_name]}')

                    # Importing step

                    if custom_field['type_id'] in (6, 12):
                        # Importing dropdown and multiselect values
                        value = self._validate_custom_field_values(custom_field, case[field_name])
                        if value:
                            if type(value) == str or type(value) == int:
                                # For single values, we need to map TestRail value to Qase value
                                testrail_key = str(value)
                                qase_value = None
                                
                                # Try to find mapping in tr_key_to_qase_id first
                                if custom_field.get('tr_key_to_qase_id') and testrail_key in custom_field['tr_key_to_qase_id']:
                                    qase_value = custom_field['tr_key_to_qase_id'][testrail_key]
                                    self.logger.log(f'[{self.project["code"]}][Tests] Using tr_key_to_qase_id mapping for global field {custom_field["name"]}: {testrail_key} -> {qase_value}')
                                elif custom_field.get('qase_values') and testrail_key in custom_field['qase_values']:
                                    # Fallback to old logic if tr_key_to_qase_id not available
                                    qase_value = custom_field['qase_values'][testrail_key]
                                    self.logger.log(f'[{self.project["code"]}][Tests] Using qase_values fallback for global field {custom_field["name"]}: {testrail_key} -> {qase_value}')
                                
                                if qase_value is None:
                                    # If no mapping found, log warning and skip this field
                                    self.logger.log(f'[{self.project["code"]}][Tests] Warning: No Qase mapping found for TestRail value {testrail_key} in global field {custom_field["name"]}', 'warning')
                                    continue
                                
                                data['custom_field'][str(custom_field['qase_id'])] = str(qase_value)
                                self.logger.log(f'[{self.project["code"]}][Tests] Set global field {custom_field["name"]} to value: {str(qase_value)}')

                            elif type(value) == list:
                                # Multiple values - handle based on field type
                                if custom_field['type_id'] == 12:  # multiselect
                                    # For multiselect, pass comma-separated string
                                    if not custom_field.get('project_id'):
                                        # For global fields, use validated values directly
                                        validated_values = self._validate_custom_field_values(custom_field, value)

                                        if validated_values:
                                            # Convert validated TestRail values to Qase IDs
                                            qase_values = []
                                            for v in validated_values:
                                                # Find the corresponding Qase ID for this TestRail value
                                                testrail_key = str(v)
                                                if custom_field.get('tr_key_to_qase_id') and testrail_key in custom_field['tr_key_to_qase_id']:
                                                    qase_id = custom_field['tr_key_to_qase_id'][testrail_key]
                                                    qase_values.append(str(qase_id))
                                                elif custom_field.get('qase_values') and testrail_key in custom_field['qase_values']:
                                                    # Fallback to old logic if tr_key_to_qase_id not available
                                                    qase_id = custom_field['qase_values'][testrail_key]
                                                    qase_values.append(str(qase_id))
                                                else:
                                                    self.logger.log(f'[{self.project["code"]}][Tests] Warning: TestRail value {v} not found in mapping for field {custom_field["name"]}', 'warning')
                                            
                                            if qase_values:
                                                data['custom_field'][str(custom_field['qase_id'])] = ','.join(qase_values)
                                                self.logger.log(f'[{self.project["code"]}][Tests] Set global multiselect field {custom_field["name"]} to values: {",".join(qase_values)}')
                                            else:
                                                self.logger.log(f'[{self.project["code"]}][Tests] No valid Qase IDs found for field {custom_field["name"]}', 'warning')
                                        else:
                                            self.logger.log(f'[{self.project["code"]}][Tests] Global field {custom_field["name"]} validation failed for value: {value}')
                                    else:
                                        # For project-specific fields, use the old logic
                                        qase_values = [str(int(v) + 1) for v in value]
                                        data['custom_field'][str(custom_field['qase_id'])] = ','.join(qase_values)
                                        self.logger.log(f'[{self.project["code"]}][Tests] Set project-specific multiselect field {custom_field["name"]} to values: {",".join(qase_values)}')
                                else:  # single select (type_id = 6)
                                    # For single select, take first value only
                                    data['custom_field'][str(custom_field['qase_id'])] = str(int(value[0]) + 1)
                                    self.logger.log(f'[{self.project["code"]}][Tests] Set single select field {custom_field["name"]} to value: {str(int(value[0]) + 1)}')

                        else:
                            self.logger.log(f'[{self.project["code"]}][Tests] Global field {custom_field["name"]} validation failed for value: {value}')
                            return None
                    else:
                        # Handle non-dropdown fields (text, number, etc.)
                        data['custom_field'][str(custom_field['qase_id'])] = self.__format_links_as_markdown(str(
                            self.attachments.check_and_replace_attachments(case[field_name], self.project['code'])))
                        self.logger.log(f'[{self.project["code"]}][Tests] Set global field {custom_field["name"]} to text value')

                else:
                    self.logger.log(f'[{self.project["code"]}][Tests] No field found for {normalized_name} or {project_specific_key}')

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
        
        # Note: Removed _validate_and_fix_custom_field_values call as it duplicates
        # the validation logic already implemented in _validate_custom_field_values
        # during field processing. The new approach is more efficient and accurate.
        
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
        """Validate custom field values against field configuration"""
        if not value:
            return None

        self.logger.log(f'[{self.project["code"]}][Tests] Validating field {custom_field["name"]} (type_id: {custom_field["type_id"]}) with value: {value}')
        
        # Special logging for field 133 to debug the validation issue
        if custom_field.get('name') == '133' or custom_field.get('id') == 133:
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 validation - custom_field: {custom_field}')
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 validation - value: {value} (type: {type(value)})')

        # For project-specific fields, use the field's own config
        if custom_field.get('project_id') and custom_field.get('project_code'):
            configs = custom_field['configs']
            self.logger.log(f'[{self.project["code"]}][Tests] Using project-specific config for field {custom_field["name"]}')

        else:
            # For global fields, find config for current project
            configs = custom_field['configs']
            project_id = self.project['testrail_id']
            matching_config = None
            
            for config in configs:
                if config['context'].get('project_ids') and project_id in config['context']['project_ids']:
                    matching_config = config
                    break
            
            if matching_config:
                configs = [matching_config]
                self.logger.log(f'[{self.project["code"]}][Tests] Using project-specific config for global field {custom_field["name"]}')

            else:
                # Use first config for global fields
                configs = [configs[0]]
                self.logger.log(f'[{self.project["code"]}][Tests] Using first config for field {custom_field["name"]}')
        
        # Special logging for field 133
        if custom_field.get('name') == '133' or custom_field.get('id') == 133:
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - configs: {configs}')
            for i, cfg in enumerate(configs):
                self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - config {i+1}: {cfg}')
                if isinstance(cfg, dict) and 'options' in cfg:
                    self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - config {i+1} options: {cfg["options"]}')


        if not configs:
            self.logger.log(f'[{self.project["code"]}][Tests] No configs found for field {custom_field["name"]}', 'warning')

            return None

        config = configs[0]
        items = config['options'].get('items', '')
        
        # Special logging for field 133
        if custom_field.get('name') == '133' or custom_field.get('id') == 133:
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - config: {config}')
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - items: {items}')
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - items type: {type(items)}')
        
        if not items:
            self.logger.log(f'[{self.project["code"]}][Tests] No items found in config for field {custom_field["name"]}', 'warning')

            return None

        # Parse items string into values dict
        values = {}
        for line in items.split('\n'):
            if ',' in line:
                key, title = line.split(',', 1)
                values[key.strip()] = title.strip()

        self.logger.log(f'[{self.project["code"]}][Tests] Field {custom_field["name"]} has {len(values)} valid values: {values}')
        
        # Special logging for field 133
        if custom_field.get('name') == '133' or custom_field.get('id') == 133:
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - parsed values: {values}')
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - value to validate: {value}')
            self.logger.log(f'[{self.project["code"]}][Tests] DEBUG: Field 133 - value in values.keys(): {str(value) in values.keys()}')

        if isinstance(value, list):
            filtered_values = []
            
            for item in value:
                if str(item) in values.keys():
                    filtered_values.append(item)
                else:
                    self.logger.log(
                        f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} has invalid value {item} (not in {list(values.keys())})',

                        'warning')
                    # Don't add invalid values to filtered_values

            if filtered_values:
                self.logger.log(f'[{self.project["code"]}][Tests] Field {custom_field["name"]} validation successful: {filtered_values}')
                return filtered_values
            else:
                self.logger.log(f'[{self.project["code"]}][Tests] No valid values found for field {custom_field["name"]}', 'warning')

                return None
        else:
            # Single value
            if str(value) in values.keys():
                self.logger.log(f'[{self.project["code"]}][Tests] Field {custom_field["name"]} validation successful: {value}')
                return [value]
            else:
                self.logger.log(
                    f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} has invalid value {value} (not in {list(values.keys())})',

                    'warning')
                return None

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

    def __normalize_custom_field_name(self, field_name: str) -> str:
        """Normalize custom field name by removing project suffix if present"""
        # Remove project suffix if it exists (e.g., "field_name_PROJECT" -> "field_name")
        if '_' in field_name:
            parts = field_name.split('_')
            # Check if the last part looks like a project code (uppercase, short)
            if len(parts[-1]) <= 5 and parts[-1].isupper():
                return '_'.join(parts[:-1])
        return field_name
