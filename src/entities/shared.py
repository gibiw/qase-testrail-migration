import asyncio

from ..service import QaseService, TestrailService
from ..support import Logger, Mappings, Pools


class SharedSteps:
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
        self.i = 0

    def import_shared_steps(self, project) -> Mappings:
        return asyncio.run(self.import_shared_steps_async(project))

    async def import_shared_steps_async(self, project) -> Mappings:
        self.logger.log(f"[{project['code']}][Shared Steps] Importing shared steps")
        limit = 250
        offset = 0

        shared_steps = []
        while True:
            tr_shared = self.testrail.get_shared_steps(project['testrail_id'], limit, offset)
            shared_steps += tr_shared
            if len(tr_shared) < limit:
                break
            offset += limit

        self.mappings.stats.add_entity_count(project['code'], 'shared_steps', 'testrail', len(shared_steps))
            
        self.logger.log(f"[{project['code']}][Shared Steps] Found {len(shared_steps)} shared steps")

        self.logger.print_status(f'[{project["code"]}] Importing shared steps', self.i, len(shared_steps), 1)
        async with asyncio.TaskGroup() as tg:
            for step in shared_steps:
                tg.create_task(self.create_shared_step(project, step, len(shared_steps)))

        self.mappings.shared_steps[project["code"]] = self.map
        
        return self.mappings

    async def create_shared_step(self, project, step, cnt):
        id = await self.pools.qs(
            self.qase.create_shared_step,
            project["code"],
            step['title'],
            step['custom_steps_separated'],
        )
        if id:
            self.mappings.stats.add_entity_count(project['code'], 'shared_steps', 'qase')
            self.map[step['id']] = id
        self.i += 1
        self.logger.print_status(f'[{project["code"]}] Importing shared steps', self.i, cnt, 1)
