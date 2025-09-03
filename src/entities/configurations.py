from ..service import QaseService, TestrailService
from ..support import Logger, Mappings, Pools

import asyncio


class Configurations:
    def __init__(
            self,
            qase_service: QaseService,
            testrail_service: TestrailService,
            logger: Logger,
            mappings: Mappings,
            pools: Pools,
    ):
        self.qase = qase_service
        self.testrail = testrail_service
        self.logger = logger
        self.mappings = mappings
        self.pools = pools

        self.map = {}
        self.logger.divider()

    def import_configurations(self, project) -> Mappings:
        return asyncio.run(self.import_configurations_async(project))

    async def import_configurations_async(self, project) -> Mappings:
        self.logger.log(f"[{project['code']}][Configurations] Importing configurations")
        configs = self.testrail.get_configurations(project['testrail_id'])
        if configs:
            self.logger.log(f"[{project['code']}][Configurations] Found {len(configs)} configurations")
            async with asyncio.TaskGroup() as tg:
                for group in configs:
                    tg.create_task(self.create_configuration_group(project, group))
        else:
            self.logger.log(f"[{project['code']}][Configurations] No configurations found")

        self.mappings.configurations[project['code']] = self.map
        
        return self.mappings

    async def create_configuration_group(self, project, group):
        self.logger.log(f"[{project['code']}][Configurations] Importing configuration group {group['name']}")

        # Check if configuration group already exists by name
        existing_groups = await self.pools.qs(self.qase.get_all_configuration_groups, project['code'])
        group_id = None
        
        for existing_group in existing_groups:
            if existing_group.title == group['name']:
                self.logger.log(f"[{project['code']}][Configurations] Configuration group '{group['name']}' already exists, using existing ID: {existing_group.id}")
                group_id = existing_group.id
                break
        
        # Create new group if not found
        if group_id is None:
            self.logger.log(f"[{project['code']}][Configurations] Creating new configuration group '{group['name']}'")
            group_id = await self.pools.qs(self.qase.create_configuration_group, project['code'], group['name'])

        if 'configs' in group and group_id:
            async with asyncio.TaskGroup() as tg:
                for config in group['configs']:
                    tg.create_task(self.create_configuration(project, config, group_id))

    async def create_configuration(self, project, config, group_id):
        self.mappings.stats.add_entity_count(project['code'], 'configurations', 'testrail')
        
        # Check if configuration already exists by name
        existing_configs = await self.pools.qs(self.qase.get_all_configurations, project['code'])
        config_id = None
        
        for existing_config in existing_configs:
            if existing_config.title == config['name']:
                self.logger.log(f"[{project['code']}][Configurations] Configuration '{config['name']}' already exists, using existing ID: {existing_config.id}")
                config_id = existing_config.id
                break
        
        # Create new configuration if not found
        if config_id is None:
            self.logger.log(f"[{project['code']}][Configurations] Creating new configuration '{config['name']}'")
            config_id = await self.pools.qs(self.qase.create_configuration, project['code'], config['name'], group_id)
        
        if config_id:
            self.mappings.stats.add_entity_count(project['code'], 'configurations', 'qase')
            self.map[config['id']] = config_id
