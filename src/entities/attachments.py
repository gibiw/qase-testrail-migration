import asyncio

from ..service import QaseService, TestrailService
from ..support import Logger, Mappings, ConfigManager as Config, Pools

from typing import List

from urllib.parse import unquote

import re
import os
import json


class Attachments:
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
        self.config = config
        self.mappings = mappings
        self.pools = pools
        self.pattern = r'!\[\]\(index\.php\?/attachments/get/([a-f0-9-]+)\)'

    def check_and_replace_attachments(self, string: str, code: str, result_id: str = None, test_id: str = None) -> str:
        if string:
            attachments = self.check_attachments(string)
            if (attachments):
                return self.replace_attachments(string=string, code = code, result_id=result_id, test_id=test_id)
        return str(string)

    def check_and_replace_attachments_from_string_array(self, string: str, code: str, result_id: str = None, test_id: str = None) -> list:
        result = []

        attachments = self.check_attachments(string)
        for attachment in attachments:
            try:
                if attachment is None or isinstance(attachment, int):
                    continue
                if attachment:
                    attachment = re.sub(r'^E_', '', str(attachment))
                if attachment and attachment not in self.mappings.attachments_map:
                    self.logger.log(f'[{code}][Attachments] Attachment {attachment} not found in attachments_map (array)',
                                    'warning')
                    self.replace_failover(attachment, code, result_id, test_id)
                if attachment and attachment in self.mappings.attachments_map and self.mappings.attachments_map[
                    attachment] and 'hash' in self.mappings.attachments_map[attachment]:
                    result.append(self.mappings.attachments_map[attachment]['hash'])
            except Exception as e:
                self.logger.log(f'[{code}][Attachments] Error processing attachment {attachment}: {e}', 'error')
        return result

    def check_and_replace_attachments_array(self, attachments: list, code: str, result_id: str = None, test_id: str = None) -> list:
        result = []
        for attachment in attachments:
            self.logger.log(f'[{code}][Attachments] Checking attachment: {attachment} in attachments_array')
            try:
                if attachment is None:
                    continue
                if attachment:
                    attachment = re.sub(r'^E_', '', str(attachment))
                if attachment and attachment not in self.mappings.attachments_map:
                    self.logger.log(f'[{code}][Attachments] Attachment {attachment} not found in attachments_map (array) in check_and_replace_attachments_array',
                                    'warning')
                    self.replace_failover(attachment, code, result_id, test_id)
                if attachment and attachment in self.mappings.attachments_map and self.mappings.attachments_map[
                    attachment] and 'hash' in self.mappings.attachments_map[attachment]:
                    self.logger.log(f'[{code}][Attachments] Attachment {attachment} found in attachments_map (array) in check_and_replace_attachments_array', 'info')
                    result.append(self.mappings.attachments_map[attachment]['hash'])
            except Exception as e:
                self.logger.log(f'[{code}][Attachments] Error processing attachment {attachment} in check_and_replace_attachments_array: {e}', 'error')

        self.logger.log(f'[{code}][Attachments] Result attachments in check_and_replace_attachments_array: {result}')
        return result

    def check_attachments(self, string: str) -> List:
        if (string):
            return re.findall(r'index\.php\?/attachments/get/([a-f0-9-]+)', str(string))
        return []

    def _get_attachment_meta(self, data) -> tuple:
        filename = "attachment"
        filename_header = data.headers.get('Content-Disposition', '')
        match = re.search(r"filename\*=UTF-8''(.+)", filename_header)
        if match:
            filename = unquote(match.group(1))

        return (filename, data.content)

    def replace_attachments(self, string: str, code: str, result_id: str = None, test_id: str = None) -> str:
        string = re.sub(r'^E_', '', string)
        try:

            matches = re.finditer(self.pattern, string)
            for match in matches:
                attachment_id = match.group(1)
                if attachment_id not in self.mappings.attachments_map:
                    self.logger.log(f'[{code}][Attachments] Attachment {attachment_id} not found in attachments_map', 'warning')
                    self.replace_failover(attachment_id, code, result_id, test_id)
                string = self.replace_string(string, code, attachment_id)
            else:
                self.logger.log(f'[{code}][Attachments] No attachments found in a string {string}', 'warning')
        except Exception as e:
            self.logger.log(f'[{code}][Attachments] Exception when replacing attachments in a string {string}: {e}', 'error')
        return string

    def replace_failover(self, attachment_id, code: str, result_id: str = None, test_id: str = None):
        try:
            result_info = ''
            if result_id is not None or test_id is not None:
                result_parts = []
                if result_id is not None:
                    result_parts.append(f'result_id={result_id}')
                if test_id is not None:
                    result_parts.append(f'test_id={test_id}')
                result_info = f' for result ({", ".join(result_parts)})'
            self.logger.log(f'[{code}][Attachments] Replacing attachment {attachment_id} in failover{result_info}')
            attachment_data = self.testrail.get_attachment(attachment_id)
            attachment_data = self._get_attachment_meta(attachment_data)
            qase_attachment = self.qase.upload_attachment(code, attachment_data)
            if qase_attachment:
                self.mappings.attachments_map[attachment_id] = qase_attachment
                self.logger.log(f'[{code}][Attachments] Attachment {attachment_id} replaced in failover{result_info}')
            else:
                self.logger.log(f'[{code}][Attachments] Attachment {attachment_id} not replaced in failover{result_info}', 'error')
        except Exception as e:
            self.logger.log(f'[{code}][Attachments] Exception when calling Qase->upload_attachment in failover{result_info}: {e}', 'error')

    def replace_string(self, string, code, attachment_id):
        return re.sub(
            f'!\\[\\]\\(index\\.php\\?/attachments/get/{attachment_id}\\)',
            f'![{self.mappings.attachments_map[attachment_id]["filename"]}]({self.mappings.attachments_map[attachment_id]["url"]})',
            string
        )

    def import_all_attachments(self) -> Mappings:
        return asyncio.run(self.import_all_attachments_async())

    async def import_all_attachments_async(self) -> Mappings:
        self.logger.log('[Attachments] Importing all attachments')
        attachments_raw = self.testrail.get_attachments_list()
        self.mappings.stats.add_attachment('testrail', len(attachments_raw))

        if self.config.get('cache'):
            self._save_cache(attachments_raw)

        async with asyncio.TaskGroup() as tg:
            for attachment in attachments_raw:
                tg.create_task(self.import_raw_attachment(attachment))

        self.logger.log(f'[Attachments] Imported {len(attachments_raw)} attachments')

        return self.mappings

    async def import_raw_attachment(self, attachment):
        self.logger.log(f'[Attachments] Importing attachment: {attachment["id"]}')

        project_ids = attachment['project_id'] if isinstance(attachment['project_id'], list) else [
            attachment['project_id']]

        if not project_ids:
            self.logger.log(f'[Attachments] Attachment {attachment["id"]} is not linked to any project', 'warning')
            return

        if len(project_ids) > 1:
            self.logger.log(f'[Attachments] Attachment {attachment["id"]} is linked to multiple projects', 'warning')

        project_id = project_ids[0]

        if project_id not in self.mappings.project_map:
            self.logger.log(f'[Attachments] Attachment {attachment["id"]} is not linked to any project', 'error')
            return

        code = self.mappings.project_map[project_id]

        try:
            meta = self._get_attachment_meta(await self.pools.tr(self.testrail.get_attachment, attachment['id']))
        except Exception as e:
            self.logger.log(f'[{code}][Attachments] Exception when calling TestRail->get_attachment: {e}', 'error')
            return

        try:
            qase_attachment = await self.pools.qs(self.qase.upload_attachment, code, meta)
            if qase_attachment:
                self.mappings.attachments_map[attachment['id']] = qase_attachment
                self.logger.log(f'[{code}][Attachments] Attachment {attachment["id"]} imported')
                self.mappings.stats.add_attachment('qase')
            else:
                self.logger.log(f'[{code}][Attachments] Attachment {attachment["id"]} not imported', 'error')
        except Exception as e:
            self.logger.log(f'[{code}][Attachments] Exception when calling Qase->upload_attachment: {e}', 'error')

    def _read_cache(self):
        return

    def _save_cache(self, attachments):
        self.logger.log('[Attachments] Saving attachments cache')
        prefix = ''
        if self.config.get('prefix'):
            prefix = self.config.get('prefix')
        filename = f'{prefix}_attachments.json'
        log_dir = './cache'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        cache_file = os.path.join(log_dir, f'{filename}')
        with open(cache_file, 'w') as f:
            f.write(json.dumps(attachments))
        self.logger.log('[Attachments] Attachments cache saved')
