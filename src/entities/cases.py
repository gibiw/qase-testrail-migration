import asyncio
import json
import re
import hashlib
import time

from ..service import QaseService, TestrailService
from ..support import Logger, Mappings, ConfigManager as Config, Pools, format_links_as_markdown, convert_testrail_date_to_iso, convert_estimate_time_to_hours

from qase.api_client_v1.models import TestStepCreate, TestCasebulkCasesInner
from .attachments import Attachments

from typing import List, Optional, Union

from urllib.parse import quote
from datetime import datetime

# Constant for maximum safe ID (int32)
MAX_SAFE_ID = 2**31 - 1  # 2,147,483,647


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
        self.attachments = Attachments(self.qase, self.testrail, self.logger, self.mappings, self.config, self.pools)
        self.total = 0
        self.logger.divider()

        self.project = None

    def import_cases(self, project: dict):
        return asyncio.run(self.import_cases_async(project))

    async def import_cases_async(self, project: dict):
        self.project = project

        async with asyncio.TaskGroup() as tg:
            if self.project['suite_mode'] in (2, 3):
                suites = await self.pools.tr(self.testrail.get_suites, self.project['testrail_id'])
                for suite in suites:
                    tg.create_task(self.import_cases_for_suite(suite['id']))
            else:
                tg.create_task(
                    self.import_cases_for_suite(None))  # Assuming None is a valid suite_id when suite_mode is not 3
        
        # Log statistics for ID mapping
        if self.mappings.case_id_mapping:
            self.logger.log(f'[{self.project["code"]}][Tests] Created {len(self.mappings.case_id_mapping)} ID mappings for cases')
            if self.config.get('tests.preserve_ids'):
                # If preserve_ids=true, save original IDs, but hash large ones
                large_ids = [orig_id for orig_id in self.mappings.case_id_mapping.keys() if orig_id > MAX_SAFE_ID]
                if large_ids:
                    self.logger.log(f'[{self.project["code"]}][Tests] {len(large_ids)} cases had large IDs that were hashed for safety (preserve_ids=true)')
                else:
                    self.logger.log(f'[{self.project["code"]}][Tests] All case IDs were preserved from TestRail (preserve_ids=true)')
            else:
                # If preserve_ids=false, all IDs were regenerated
                self.logger.log(f'[{self.project["code"]}][Tests] All case IDs were regenerated due to preserve_ids=false')
            
            # Check if all generated IDs are safe
            unsafe_ids = [qase_id for qase_id in self.mappings.case_id_mapping.values() if qase_id > MAX_SAFE_ID]
            if unsafe_ids:
                self.logger.log(f'[{self.project["code"]}][Tests] WARNING: {len(unsafe_ids)} generated IDs are still too large! This should not happen.')
            else:
                self.logger.log(f'[{self.project["code"]}][Tests] All generated IDs are within safe range (≤ {MAX_SAFE_ID})')
        else:
            self.logger.log(f'[{self.project["code"]}][Tests] No ID mappings created')

    async def import_cases_for_suite(self, suite_id):
        offset = 0
        # Set limit based on enterprise setting: 20 for enterprise, 100 for cloud
        limit = 20 if self.config.get('qase.enterprise') else 100
        while True:
            count = await self.process_cases(suite_id, offset, limit)
            if count < limit:
                break
            offset += limit

    async def process_cases(self, suite_id: int, offset: int, limit: int):
        try:
            if suite_id is None:
                suite_id = 0
            cases = await self.pools.tr(self.testrail.get_cases, self.project['testrail_id'], suite_id, limit, offset)
            self.mappings.stats.add_entity_count(self.project['code'], 'cases', 'testrail', cases['size'])
            if cases:
                self.logger.print_status('[' + self.project['code'] + '] Importing test cases', self.total,
                                         self.total + cases['size'], 1)
                self.logger.log(
                    f'[{self.project["code"]}][Tests] Importing {cases["size"]} cases from {offset} to {offset + limit} for suite {suite_id}')
                data = await self._prepare_cases(cases)
                if data:
                    if self.config.get('qase.enterprise'):
                        time.sleep(5)  # To avoid hitting rate limits
                    status = await self.pools.qs(self.qase.create_cases, self.project['code'], data)
                    if status:
                        self.mappings.stats.add_entity_count(self.project['code'], 'cases', 'qase', cases['size'])
                self.total = self.total + cases['size']
                self.logger.print_status('[' + self.project['code'] + '] Importing test cases', self.total, self.total,
                                         1)
            return cases['size']
        except Exception as e:
            self.logger.log(f"[{self.project['code']}][Tests] Error processing cases for suite {suite_id}: {e}",
                            'error')
            return 0

    async def _prepare_cases(self, cases: List) -> List:
        result = []
        async with asyncio.TaskGroup() as tg:
            for case in cases['cases']:
                tg.create_task(self._prepare_case(case, result))

        return result

    async def _prepare_case(self, case, result):
        try:
            original_id = case['id']
            
            # Check preserve_ids setting
            if self.config.get('tests.preserve_ids'):
                # preserve_ids enabled - save original IDs from TestRail
                if original_id <= MAX_SAFE_ID:  # ID fits in int32
                    # Save original ID
                    safe_id = int(original_id)
                    self.logger.log(f'[{self.project["code"]}][Tests] preserve_ids enabled, using original ID: {safe_id} for case {case["title"]}')
                else:
                    # ID too large, but preserve_ids=true, so hash it
                    hashed_id = int(hashlib.md5(str(original_id).encode()).hexdigest()[:8], 16)
                    safe_id = hashed_id % MAX_SAFE_ID  # Limit hash to safe range
                    self.logger.log(f'[{self.project["code"]}][Tests] preserve_ids enabled, original ID {original_id} too large, using hashed ID: {safe_id} for case {case["title"]}')
            else:
                # preserve_ids disabled - generate new IDs for all cases
                if original_id <= MAX_SAFE_ID:  # ID fits in int32
                    # Generate new ID even for small ones
                    import time
                    safe_id = int(time.time() * 1000) % MAX_SAFE_ID
                    self.logger.log(f'[{self.project["code"]}][Tests] preserve_ids disabled, generated new ID: {safe_id} for case {case["title"]} (original: {original_id})')
                else:
                    # ID too large, hash it
                    hashed_id = int(hashlib.md5(str(original_id).encode()).hexdigest()[:8], 16)
                    safe_id = hashed_id % MAX_SAFE_ID  # Limit hash to safe range
                    self.logger.log(f'[{self.project["code"]}][Tests] preserve_ids disabled, original ID {original_id} too large, using hashed ID: {safe_id} for case {case["title"]}')
            
            # Save mapping of original ID to generated (or same) ID
            self.mappings.add_case_id_mapping(original_id, safe_id)
            self.logger.log(f'[{self.project["code"]}][Tests] Created ID mapping: TestRail {original_id} -> Qase {safe_id}')
            
            # Additional safety check - all IDs must fit in int32
            if safe_id > MAX_SAFE_ID:
                # If ID is still too large, force it to safe range
                safe_id = safe_id % MAX_SAFE_ID
                self.logger.log(f'[{self.project["code"]}][Tests] WARNING: Generated ID was still too large, forced to safe range: {safe_id}')
                # Update mapping
                self.mappings.add_case_id_mapping(original_id, safe_id)
            
            data = {
                'id': safe_id,
                'title': case['title'],
                'created_at': str(datetime.fromtimestamp(case['created_on'])),
                'updated_at': str(datetime.fromtimestamp(case['updated_on'])),
                'author_id': self.mappings.get_user_id(case['created_by']),
                'steps': [],
                'attachments': [],
                'is_flaky': 0,
                'custom_field': {},
            }
            
            # Save original ID in custom field if preserve_ids is enabled
            if not self.config.get('tests.preserve_ids') and hasattr(self.mappings, 'testrail_original_id_field_id'):
                data['custom_field'][str(self.mappings.testrail_original_id_field_id)] = str(original_id)
                self.logger.log(f'[{self.project["code"]}][Tests] Stored original ID {original_id} in custom field for case {case["title"]}')

            # import custom fields
            data = self._import_custom_fields_for_case(case=case, data=data)
            data = await self._get_attachments_for_case(case=case, data=data)

            data = self._set_priority(case=case, data=data)
            data = self._set_type(case=case, data=data)
            data = self._set_status(case=case, data=data)
            data = self._set_suite(case=case, data=data)
            data = self._set_refs(case=case, data=data)
            data = self._set_milestone(case=case, data=data, code=self.project['code'])
            data = self._set_estimate(case=case, data=data)

            result.append(
                TestCasebulkCasesInner(
                    **data
                )
            )

            self.logger.log("Prepared test: " + data['title'] + " - " + str(data['suite_id']))
        except Exception as e:
            self.logger.log(f'[{self.project["code"]}][Tests] Failed to prepare case {case["title"]}: {e}', 'error')
            self.logger.log(f'[{self.project["code"]}][Tests] Case: {case}',)
            self.logger.log(f'[{self.project["code"]}][Tests] Data: {data}', )

    # Done
    def _set_refs(self, case: dict, data: dict) -> dict:
        if not (self.mappings.refs_id and case.get('refs') and self.config.get('tests.refs.enable')):
            return data

        refs = [ref.strip() for ref in case['refs'].split(',')]
        url = self.config.get('tests.refs.url').rstrip('/')

        processed_refs = [self._get_ref(ref, url) for ref in refs]
        data['custom_field'][str(self.mappings.refs_id)] = '\n'.join(processed_refs)

        return data

    @staticmethod
    def _get_ref(ref: str, url: str) -> str:
        if ref.startswith('http'):
            link_url = quote(ref, safe="/:")
        else:
            link_url = quote(f"{url}/{ref}", safe="/:")
        
        # Wrap in markdown link format
        return f"[{ref}]({link_url})"

    async def _get_attachments_for_case(self, case: dict, data: dict) -> dict:
        self.logger.log(f'[{self.project["code"]}][Tests] Getting attachments for case {case["title"]}')
        try:
            attachments = await self.pools.tr(self.testrail.get_attachments_case, case['id'])
        except Exception as e:
            self.logger.log(f'[{self.project["code"]}][Tests] Failed to get attachments for case {case["title"]}: {e}',
                            'error')
            return data
        self.logger.log(
            f'[{self.project["code"]}][Tests] Found {len(attachments["attachments"])} attachments for case {case["title"]}')
        for attachment in attachments['attachments']:
            try:
                id = attachment['id']
                if 'data_id' in attachment:
                    id = attachment['data_id']
                if id in self.mappings.attachments_map:
                    data['attachments'].append(self.mappings.attachments_map[id]['hash'])
            except Exception as e:
                self.logger.log(
                    f'[{self.project["code"]}][Tests] Failed to get attachment for case {case["title"]}: {e}', 'error')
        return data

    # Done
    def _import_custom_fields_for_case(self, case: dict, data: dict) -> dict:
        for field_name in case:
            if field_name.startswith('custom_'):
                normalized_name = self.__normalize_custom_field_name(field_name[len('custom_'):])
                
                # Look for project-specific field first
                project_specific_key = f"{normalized_name}_{self.project['code']}"
                if project_specific_key in self.mappings.custom_fields and case[field_name]:
                    custom_field = self.mappings.custom_fields[project_specific_key]
                    self.logger.log(f'[{self.project["code"]}][Tests] Using project-specific field {project_specific_key} for case {case["title"]} with value: {case[field_name]}')
                    self.logger.log(f'[{self.project["code"]}][Tests] Field type: {custom_field["type_id"]} (6=selectbox, 12=multiselect)')
                    self.logger.log(f'[{self.project["code"]}][Tests] Field qase_id: {custom_field["qase_id"]}')
                    self.logger.log(f'[{self.project["code"]}][Tests] Field name: {custom_field["name"]}')
                    
                    # Importing step

                    if custom_field['type_id'] in (6, 12):
                        # Importing dropdown and multiselect values
                        value = self._validate_custom_field_values(custom_field, case[field_name])
                        if value:
                            if type(value) == str or type(value) == int:
                                # Single value - use proper mapping if available
                                if custom_field.get('tr_key_to_qase_id') and str(value) in custom_field['tr_key_to_qase_id']:
                                    qase_id = custom_field['tr_key_to_qase_id'][str(value)]
                                    data['custom_field'][str(custom_field['qase_id'])] = str(qase_id)
                                    self.logger.log(f'[{self.project["code"]}][Tests] Set field {custom_field["name"]} using mapping {value} -> {qase_id}')
                                else:
                                    # Fallback - use value directly without +1 offset
                                    data['custom_field'][str(custom_field['qase_id'])] = str(value)
                                    self.logger.log(f'[{self.project["code"]}][Tests] Set field {custom_field["name"]} to value: {str(value)}')
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
                                        # For project-specific fields, use proper mapping
                                        qase_values = []
                                        for v in value:
                                            testrail_key = str(v)
                                            if custom_field.get('tr_key_to_qase_id') and testrail_key in custom_field['tr_key_to_qase_id']:
                                                qase_id = custom_field['tr_key_to_qase_id'][testrail_key]
                                                qase_values.append(str(qase_id))
                                            else:
                                                # Fallback - use value directly without +1 offset
                                                qase_values.append(str(v))
                                        data['custom_field'][str(custom_field['qase_id'])] = ','.join(qase_values)
                                        self.logger.log(f'[{self.project["code"]}][Tests] Set project-specific multiselect field {custom_field["name"]} to values: {",".join(qase_values)}')
                                else:  # single select (type_id = 6)
                                    # For single select, take first value only
                                    if custom_field.get('tr_key_to_qase_id') and str(value[0]) in custom_field['tr_key_to_qase_id']:
                                        qase_id = custom_field['tr_key_to_qase_id'][str(value[0])]
                                        data['custom_field'][str(custom_field['qase_id'])] = str(qase_id)
                                        self.logger.log(f'[{self.project["code"]}][Tests] Set single select field {custom_field["name"]} using mapping {value[0]} -> {qase_id}')
                                    else:
                                        # Fallback - use value directly without +1 offset
                                        data['custom_field'][str(custom_field['qase_id'])] = str(value[0])
                                        self.logger.log(f'[{self.project["code"]}][Tests] Set single select field {custom_field["name"]} to value: {str(value[0])}')
                    elif custom_field['type_id'] == 8:
                        # Handle datepicker fields (type 8) - convert TestRail date format to ISO format
                        field_value = str(case[field_name])
                        converted_date = convert_testrail_date_to_iso(field_value)
                        data['custom_field'][str(custom_field['qase_id'])] = converted_date
                        self.logger.log(f'[{self.project["code"]}][Tests] Set datepicker field "{custom_field["name"]}" to converted date: "{converted_date}" (original: "{field_value}")')
                    else:
                        field_value = format_links_as_markdown(str(
                            self.attachments.check_and_replace_attachments(case[field_name], self.project['code'])))
                        
                        # Special handling for preconds field - only set preconditions system field, skip custom field
                        if normalized_name == 'preconds':
                            data['preconditions'] = field_value
                            self.logger.log(f'[{self.project["code"]}][Tests] Set preconds field value to preconditions system field (skipped custom field)')
                        else:
                            data['custom_field'][str(custom_field['qase_id'])] = field_value
                            self.logger.log(f'[{self.project["code"]}][Tests] Set field "{custom_field["name"]}" to value: "{field_value}"')
                            
                # Fallback to original field name for backward compatibility
                elif normalized_name in self.mappings.custom_fields and case[field_name]:
                    custom_field = self.mappings.custom_fields[normalized_name]
                    self.logger.log(f'[{self.project["code"]}][Tests] Using global field {normalized_name} for case {case["title"]} with value: {case[field_name]}')
                    self.logger.log(f'[{self.project["code"]}][Tests] Field type: {custom_field["type_id"]} (6=selectbox, 12=multiselect)')
                    self.logger.log(f'[{self.project["code"]}][Tests] Field qase_id: {custom_field["qase_id"]}')
                    self.logger.log(f'[{self.project["code"]}][Tests] Field name: {custom_field["name"]}')
                    # Importing step

                    if custom_field['type_id'] in (6, 12):
                        # Importing dropdown and multiselect values
                        value = self._validate_custom_field_values(custom_field, case[field_name])
                        if value:
                            if type(value) == str or type(value) == int:
                                # Single value - use proper mapping if available
                                if custom_field.get('tr_key_to_qase_id') and str(value) in custom_field['tr_key_to_qase_id']:
                                    qase_id = custom_field['tr_key_to_qase_id'][str(value)]
                                    data['custom_field'][str(custom_field['qase_id'])] = str(qase_id)
                                    self.logger.log(f'[{self.project["code"]}][Tests] Set global field {custom_field["name"]} using mapping {value} -> {qase_id}')
                                else:
                                    # Fallback - use value directly without +1 offset
                                    data['custom_field'][str(custom_field['qase_id'])] = str(value)
                                    self.logger.log(f'[{self.project["code"]}][Tests] Set global field {custom_field["name"]} to value: {str(value)}')
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
                                        # For project-specific fields, use proper mapping
                                        qase_values = []
                                        for v in value:
                                            testrail_key = str(v)
                                            if custom_field.get('tr_key_to_qase_id') and testrail_key in custom_field['tr_key_to_qase_id']:
                                                qase_id = custom_field['tr_key_to_qase_id'][testrail_key]
                                                qase_values.append(str(qase_id))
                                            else:
                                                # Fallback - use value directly without +1 offset
                                                qase_values.append(str(v))
                                        data['custom_field'][str(custom_field['qase_id'])] = ','.join(qase_values)
                                        self.logger.log(f'[{self.project["code"]}][Tests] Set project-specific multiselect field {custom_field["name"]} to values: {",".join(qase_values)}')
                                else:  # single select (type_id = 6)
                                    # For single select, take first value only
                                    if custom_field.get('tr_key_to_qase_id') and str(value[0]) in custom_field['tr_key_to_qase_id']:
                                        qase_id = custom_field['tr_key_to_qase_id'][str(value[0])]
                                        data['custom_field'][str(custom_field['qase_id'])] = str(qase_id)
                                        self.logger.log(f'[{self.project["code"]}][Tests] Set single select field {custom_field["name"]} using mapping {value[0]} -> {qase_id}')
                                    else:
                                        # Fallback - use value directly without +1 offset
                                        data['custom_field'][str(custom_field['qase_id'])] = str(value[0])
                                        self.logger.log(f'[{self.project["code"]}][Tests] Set single select field {custom_field["name"]} to value: {str(value[0])}')
                        else:
                            self.logger.log(f'[{self.project["code"]}][Tests] Global field {custom_field["name"]} validation failed for value: {value}')
                            return data
                    elif custom_field['type_id'] == 8:
                        # Handle datepicker fields (type 8) - convert TestRail date format to ISO format
                        field_value = str(case[field_name])
                        converted_date = convert_testrail_date_to_iso(field_value)
                        data['custom_field'][str(custom_field['qase_id'])] = converted_date
                        self.logger.log(f'[{self.project["code"]}][Tests] Set global datepicker field "{custom_field["name"]}" to converted date: "{converted_date}" (original: "{field_value}")')
                    else:
                        # Handle non-dropdown fields (text, number, etc.)
                        field_value = format_links_as_markdown(str(
                            self.attachments.check_and_replace_attachments(case[field_name], self.project['code'])))
                        
                        # Special handling for preconds field - only set preconditions system field, skip custom field
                        if normalized_name == 'preconds':
                            data['preconditions'] = field_value
                            self.logger.log(f'[{self.project["code"]}][Tests] Set preconds field value to preconditions system field (skipped custom field)')
                        else:
                            data['custom_field'][str(custom_field['qase_id'])] = field_value
                            self.logger.log(f'[{self.project["code"]}][Tests] Set global field {custom_field["name"]} to text value')
                else:
                    self.logger.log(f'[{self.project["code"]}][Tests] No field found for {normalized_name} or {project_specific_key}')

            if field_name[len('custom_'):] == 'testrail_bdd_scenario' and case[field_name] is not None:
                steps = []
                i = 1
                try:
                    parsed_data = json.loads(case[field_name])
                except Exception as e:
                    self.logger.log(
                        f'[{self.project["code"]}][Tests] Case {case["title"]} has invalid step {case[field_name]}: {e}',
                        'warning')
                    continue
                for step in parsed_data:
                    if 'content' not in step:
                        self.logger.log(f'[{self.project["code"]}][Tests] Case {case["title"]} has invalid step {step}',
                                        'warning')
                    else:
                        action = self.attachments.check_and_replace_attachments(step['content'], self.project['code'])
                        action = action.strip()

                        if action == '' or action == ' ':
                            action = 'No action'
                        steps.append(
                            TestStepCreate(
                                action=format_links_as_markdown(action),
                                expected_result=None,
                                position=i
                            )
                        )
                        i += 1
                else:
                    self.logger.log(f'[{self.project["code"]}][Tests] Case {case["title"]} has invalid step {step}',
                                    'warning')
                data['steps'] = steps

            if field_name[len('custom_'):] in self.mappings.step_fields and case[field_name]:
                steps = []
                i = 1
                for step in case[field_name]:
                    action = self.attachments.check_and_replace_attachments(step['content'], self.project['code'])
                    expected = self.attachments.check_and_replace_attachments(step['expected'], self.project['code'])
                    input_data = self.attachments.check_and_replace_attachments(step.get('additional_info', ''),
                                                                                self.project['code'])

                    action = action.strip()
                    expected = expected.strip()
                    input_data = input_data.strip()

                    if (action != '' or (action == '' and expected != '')):
                        if action == '' or action == ' ':
                            action = 'No action'
                        steps.append(
                            TestStepCreate(
                                action=format_links_as_markdown(action),
                                expected_result=format_links_as_markdown(expected),
                                data=format_links_as_markdown(input_data),
                                position=i
                            )
                        )
                        i += 1
                    else:
                        self.logger.log(f'[{self.project["code"]}][Tests] Case {case["title"]} has invalid step {step}',
                                        'warning')
                data['steps'] = steps
        return data

    # Done. Method validates if custom field value exists (skip)
    def _validate_custom_field_values(self, custom_field: dict, value: Union[str, List]) -> Optional[Union[str, list]]:
        """Validate custom field values against field configuration"""
        if not value:
            return None

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

        if not configs:
            self.logger.log(f'[{self.project["code"]}][Tests] No configs found for field {custom_field["name"]}', 'warning')
            return None

        config = configs[0]
        items = config['options'].get('items', '')
        
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
                return filtered_values
            else:
                self.logger.log(f'[{self.project["code"]}][Tests] No valid values found for field {custom_field["name"]}', 'warning')
                return None
        else:
            # Single value
            if str(value) in values.keys():
                return [value]
            else:
                self.logger.log(
                    f'[{self.project["code"]}][Tests] Custom field {custom_field["name"]} has invalid value {value} (not in {list(values.keys())})',
                    'warning')
                return None

    def __split_values(self, string: str, delimiter: str = ',') -> dict:
        items = string.split('\n')  # split items into a list
        result = {}
        for item in items:
            if item != '' and item != None:
                key, value = item.split(delimiter)
                result[key] = value
        return result

    # Done
    def _set_priority(self, case: dict, data: dict) -> dict:
        data['priority'] = self.mappings.priorities[case['priority_id']] if case[
                                                                                'priority_id'] in self.mappings.priorities else self.mappings.default_priority
        return data

    # Done
    def _set_type(self, case: dict, data: dict) -> dict:
        data['type'] = self.mappings.types[case['type_id']] if case['type_id'] in self.mappings.types else 1
        return data

    def _set_status(self, case: dict, data: dict) -> dict:
        # Not used yet, as testrail doesn't return case statuses
        return data
        data['status'] = self.mappings.case_statuses[case['status_id']] if case[
                                                                               'status_id'] in self.mappings.case_statuses else 1
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

    def _set_estimate(self, case: dict, data: dict) -> dict:
        """Set estimate field with converted time value"""
        if hasattr(self.mappings, 'estimate_field_id') and self.mappings.estimate_field_id:
            # Check if case has estimate field
            if 'estimate' in case and case['estimate']:
                # Convert estimate time to hours
                converted_estimate = convert_estimate_time_to_hours(case['estimate'])
                data['custom_field'][str(self.mappings.estimate_field_id)] = converted_estimate
                self.logger.log(f'[{self.project["code"]}][Tests] Set estimate field to: "{converted_estimate}" (original: "{case["estimate"]}")')
            else:
                self.logger.log(f'[{self.project["code"]}][Tests] Case {case["title"]} has no estimate value')
        else:
            self.logger.log(f'[{self.project["code"]}][Tests] Estimate field not available in mappings')
        return data




    def get_case_id_mapping(self) -> dict:
        """
        Returns the mapping of original TestRail IDs to generated Qase IDs
        """
        return self.mappings.case_id_mapping

    def __normalize_custom_field_name(self, field_name: str) -> str:
        """
        Normalize custom field name by removing common prefixes.
        Supports both 'case_numbers' and 'numbers' -> 'numbers'
        """
        # Remove common prefixes that might be added to field names
        prefixes_to_remove = ['case_', 'test_', 'tr_']
        
        for prefix in prefixes_to_remove:
            if field_name.startswith(prefix):
                field_name = field_name[len(prefix):]
                break
        
        return field_name
