import asyncio
import json

from ..service import QaseService, TestrailService
from ..support import Logger, Mappings, ConfigManager as Config, Pools


class Fields:
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
        self.logger = logger
        self.mappings = mappings
        self.config = config
        self.pools = pools

        self.refs_id = None
        self.system_fields = []

        self.map = {}
        self.logger.divider()

    def import_fields(self):
        return asyncio.run(self.import_fields_async())

    async def import_fields_async(self):
        self.logger.log('[Fields] Loading custom fields from Qase')
        qase_custom_fields = await self.pools.qs(self.qase.get_case_custom_fields)
        self.logger.log('[Fields] Loading custom fields from TestRail')
        testrail_custom_fields = await self.pools.tr(self.testrail.get_case_fields)
        self.logger.log('[Fields] Loading system fields from Qase')
        qase_system_fields = await self.pools.qs(self.qase.get_system_fields)
        for field in qase_system_fields:
            self.system_fields.append(field.to_dict())

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._create_types_map())
            tg.create_task(self._create_priorities_map())
            tg.create_task(self._create_result_statuses_map())

        total = len(testrail_custom_fields)

        self.logger.log(f'[Fields] Found {str(total)} custom fields')

        fields_to_import = self._get_fields_to_import(testrail_custom_fields)

        i = 0
        self.logger.print_status('Importing custom fields', i, total)
        self.mappings.stats.add_custom_field('testrail', total)
        async with asyncio.TaskGroup() as tg:
            for field in testrail_custom_fields:
                i += 1
                if field['name'] in fields_to_import and field['is_active']:
                    if field['type_id'] in self.mappings.custom_fields_type:
                        tg.create_task(self._create_custom_field(
                            field, qase_custom_fields))
                else:
                    self.logger.log(
                        f'[Fields] Skipping custom field: {field["name"]}')

                if field['type_id'] == 10:
                    self.mappings.step_fields.append(field['name'])
                self.logger.print_status('Importing custom fields', i, total)

        await self._create_refs_field(qase_custom_fields)
        return self.mappings

    def _get_fields_to_import(self, custom_fields):
        self.logger.log('[Fields] Building a map for fields to import')
        fields_to_import = self.config.get('tests.fields')
        if fields_to_import is not None and len(fields_to_import) == 0 and not fields_to_import:
            for field in custom_fields:
                if field['system_name'].startswith('custom_'):
                    fields_to_import.append(field['name'])
        return fields_to_import

    async def _create_custom_field(self, field, qase_fields):
        # Skip if field already exists
        if qase_fields and len(qase_fields) > 0:
            for qase_field in qase_fields:
                if qase_field.title == field['label'] and self.mappings.custom_fields_type[field['type_id']] == self.mappings.qase_fields_type[qase_field.type.lower()]:
                    self.logger.log(
                        '[Fields] Custom field already exists: ' + field['label'])
                    if qase_field.type.lower() in ("selectbox", "multiselect", "radio"):
                        field['qase_values'] = {}
                        values = json.loads(qase_field.value)
                        for value in values:
                            field['qase_values'][value['id']] = value['title']
                    field['qase_id'] = qase_field.id
                    self.mappings.custom_fields[field['name']] = field
                    return

        data = self.qase.prepare_custom_field_data(field, self.mappings)
        qase_id = await self.pools.qs(self.qase.create_custom_field, data)
        if qase_id > 0:
            self.logger.log('[Fields] Custom field created: ' + field['label'])
            field['qase_id'] = qase_id
            self.mappings.custom_fields[field['name']] = field
            self.mappings.stats.add_custom_field('qase')

    async def _create_refs_field(self, qase_custom_fields):
        if self.config.get('tests.refs.enable'):
            if qase_custom_fields and len(qase_custom_fields) > 0:
                for qase_field in qase_custom_fields:
                    if qase_field.title == 'Refs':
                        self.logger.log('Refs field found')
                        self.mappings.refs_id = qase_field.id

            if not self.mappings.refs_id:
                self.logger.log(
                    '[Fields] Refs field not found. Creating a new one')
                data = {
                    'title': 'Refs',
                    'entity': 0,  # 0 - case, 1 - run, 2 - defect,
                    'type': 2,
                    'is_filterable': True,
                    'is_visible': True,
                    'is_required': False,
                    'is_enabled_for_all_projects': True,
                }
                self.mappings.refs_id = await self.pools.qs(self.qase.create_custom_field, data)

    async def _create_types_map(self):
        self.logger.log('[Fields] Creating types map')

        tr_types = await self.pools.tr(self.testrail.get_case_types)
        qase_types = []

        for field in self.system_fields:
            if field['slug'] == 'type':
                for option in field['options']:
                    qase_types.append(option)

        for tr_type in tr_types:
            self.mappings.types[tr_type['id']] = 1
            for qase_type in qase_types:
                if tr_type['name'].lower() == qase_type['title'].lower():
                    self.mappings.types[tr_type['id']] = int(qase_type['id'])

        self.logger.log('[Fields] Types map was created')

    async def _create_priorities_map(self):
        self.logger.log('[Fields] Creating priorities map')

        tr_priorities = await self.pools.tr(self.testrail.get_priorities)
        qase_priorities = []

        for field in self.system_fields:
            if field['slug'] == 'priority':
                for option in field['options']:
                    qase_priorities.append(option)

        for tr_priority in tr_priorities:
            self.mappings.priorities[tr_priority['id']] = 1
            for qase_priority in qase_priorities:
                if tr_priority['name'].lower() == qase_priority['title'].lower():
                    self.mappings.priorities[tr_priority['id']] = int(
                        qase_priority['id'])

        self.logger.log('[Fields] Priorities map was created')

    async def _create_result_statuses_map(self):
        self.logger.log('[Fields] Creating statuses map')

        tr_statuses = await self.pools.tr(self.testrail.get_result_statuses)
        qase_statuses = []

        for field in self.system_fields:
            if field['slug'] == 'result_status':
                for option in field['options']:
                    qase_statuses.append(option)

        for tr_status in tr_statuses:
            self.mappings.result_statuses[tr_status['id']] = 'skipped'
            for qase_status in qase_statuses:
                if tr_status['label'].lower() == qase_status['title'].lower():
                    self.mappings.result_statuses[tr_status['id']
                                                  ] = qase_status['slug']

        self.logger.log('[Fields] Result statuses map was created')

    def _create_case_statuses_map(self):
        self.logger.log('[Fields] Creating case statuses map')

        tr_statuses = self.testrail.get_case_statuses()
        qase_statuses = []

        for field in self.system_fields:
            if field['slug'] == 'status':
                for option in field['options']:
                    qase_statuses.append(option)

        for tr_status in tr_statuses:
            self.mappings.case_statuses[tr_status['case_status_id']] = 1
            for qase_status in qase_statuses:
                if tr_status['name'].lower() == qase_status['slug'].lower():
                    self.mappings.case_statuses[tr_status['case_status_id']
                                                ] = qase_status['id']

        self.logger.log('[Fields] Case statuses map was created')
