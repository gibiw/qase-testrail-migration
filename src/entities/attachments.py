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
        # Pattern for markdown format: ![](index.php?/attachments/get/123)
        self.pattern = r'!\[\]\(index\.php\?/attachments/get/([a-f0-9-]+)\)'
        # Pattern for HTML img tags with various formats
        self.html_img_pattern = r'<img[^>]*(?:src=["\']index\.php\?/attachments/get/([a-f0-9-]+)|data-attachment-id=["\']([a-f0-9-]+)|data-original-src=["\']index\.php\?/attachments/get/([a-f0-9-]+))[^>]*>'

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
        """
        Extract attachment IDs from both markdown and HTML image formats.
        Returns a list of unique attachment IDs found in the string.
        """
        if not string:
            return []
        
        attachment_ids = set()
        string_str = str(string)
        
        # Find markdown format: ![](index.php?/attachments/get/123)
        markdown_matches = re.findall(r'index\.php\?/attachments/get/([a-f0-9-]+)', string_str)
        attachment_ids.update(markdown_matches)
        
        # Find HTML img tags with src attribute: <img src="index.php?/attachments/get/123#_t=...">
        html_src_matches = re.findall(r'<img[^>]*src=["\']index\.php\?/attachments/get/([a-f0-9-]+)', string_str)
        attachment_ids.update(html_src_matches)
        
        # Find HTML img tags with data-attachment-id attribute: <img ... data-attachment-id="123">
        html_data_id_matches = re.findall(r'<img[^>]*data-attachment-id=["\']([a-f0-9-]+)', string_str)
        attachment_ids.update(html_data_id_matches)
        
        # Find HTML img tags with data-original-src attribute: <img ... data-original-src="index.php?/attachments/get/123">
        html_data_src_matches = re.findall(r'<img[^>]*data-original-src=["\']index\.php\?/attachments/get/([a-f0-9-]+)', string_str)
        attachment_ids.update(html_data_src_matches)
        
        return list(attachment_ids)

    def _get_attachment_meta(self, data) -> tuple:
        filename = "attachment"
        filename_header = data.headers.get('Content-Disposition', '')
        match = re.search(r"filename\*=UTF-8''(.+)", filename_header)
        if match:
            filename = unquote(match.group(1))

        return (filename, data.content)

    def replace_attachments(self, string: str, code: str, result_id: str = None, test_id: str = None) -> str:
        """
        Replace both markdown and HTML image references with Qase markdown format.
        Converts: ![](index.php?/attachments/get/123) or <img src="..."> to ![filename](qase_url)
        """
        string = re.sub(r'^E_', '', string)
        try:
            # First, handle markdown format: ![](index.php?/attachments/get/123)
            matches = re.finditer(self.pattern, string)
            for match in matches:
                attachment_id = match.group(1)
                if attachment_id not in self.mappings.attachments_map:
                    self.logger.log(f'[{code}][Attachments] Attachment {attachment_id} not found in attachments_map', 'warning')
                    self.replace_failover(attachment_id, code, result_id, test_id)
                string = self.replace_string_markdown(string, code, attachment_id)
            
            # Then, handle HTML img tags: <img src="index.php?/attachments/get/123" ...>
            # Find all HTML img tags with attachment references
            html_img_pattern = r'<img[^>]*(?:src=["\']index\.php\?/attachments/get/([a-f0-9-]+)|data-attachment-id=["\']([a-f0-9-]+)|data-original-src=["\']index\.php\?/attachments/get/([a-f0-9-]+))[^>]*>'
            html_matches = list(re.finditer(html_img_pattern, string))
            # Process matches in reverse order to avoid index shifting when replacing
            for match in reversed(html_matches):
                # Get the first non-None group (could be from src, data-attachment-id, or data-original-src)
                attachment_id = next((g for g in match.groups() if g), None)
                if attachment_id:
                    if attachment_id not in self.mappings.attachments_map:
                        self.logger.log(f'[{code}][Attachments] Attachment {attachment_id} not found in attachments_map (HTML)', 'warning')
                        self.replace_failover(attachment_id, code, result_id, test_id)
                    string = self.replace_string_html(string, code, attachment_id, match.group(0))
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

    def replace_string_markdown(self, string, code, attachment_id):
        """
        Replace markdown format image reference with Qase markdown format.
        Converts: ![](index.php?/attachments/get/123) to ![filename](qase_url)
        """
        if attachment_id not in self.mappings.attachments_map:
            return string
        return re.sub(
            f'!\\[\\]\\(index\\.php\\?/attachments/get/{re.escape(attachment_id)}\\)',
            f'![{self.mappings.attachments_map[attachment_id]["filename"]}]({self.mappings.attachments_map[attachment_id]["url"]})',
            string
        )
    
    def replace_string_html(self, string, code, attachment_id, html_tag):
        """
        Replace HTML img tag with Qase markdown format.
        Converts: <img src="index.php?/attachments/get/123" ...> to ![filename](qase_url)
        """
        if attachment_id not in self.mappings.attachments_map:
            return string
        
        # Escape the HTML tag for regex
        escaped_tag = re.escape(html_tag)
        # Replace the entire HTML img tag with markdown
        filename = self.mappings.attachments_map[attachment_id]["filename"]
        url = self.mappings.attachments_map[attachment_id]["url"]
        markdown = f'![{filename}]({url})'
        
        return re.sub(escaped_tag, markdown, string)

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
