import asyncio

from ..service import QaseService, QaseScimService, TestrailService
from ..support import Logger, Mappings, ConfigManager as Config, Pools


class Users:
    def __init__(
        self,
        qase_service: QaseService,
        testrail_service: TestrailService,
        logger: Logger,
        mappings: Mappings,
        config: Config,
        pools: Pools,
        scim_service: QaseScimService = None,
    ):
        self.qase = qase_service
        self.scim = scim_service
        self.testrail = testrail_service
        self.logger = logger
        self.mappings = mappings
        self.config = config
        self.pools = pools
        self.map = {}  # This is a map of TestRail user ids to Qase user ids. Used for mapping users to groups
        self.active_ids = []  # This is a list of Qase active users that should be added to groups
        self.testrail_users = []
        self.logger.divider()

    def import_users(self):
        return asyncio.run(self.import_users_async())

    async def import_users_async(self):
        await self.get_testrail_users()

        if self.scim is not None:
            await self.create_users()
            if self.config.get('groups.create'):
                await self.create_root_group()
                await self.import_groups()

        await self.build_map()

        return self.mappings

    async def build_map(self):
        self.logger.log("[Users] Building users map")
        qase_users = await self.pools.qs_gen_all(self.qase.get_all_users)
        self.mappings.stats.add_user('qase', len(qase_users))
        self.mappings.stats.add_user('testrail', len(self.testrail_users))
        i = 0
        total = len(self.testrail_users)
        self.logger.print_status('Building users map', i, total)
        for testrail_user in self.testrail_users:
            i += 1
            flag = False
            for qase_user in qase_users:
                qase_user = qase_user.to_dict()
                if testrail_user['email'].lower() == qase_user['email'].lower():
                    self.mappings.users[testrail_user['id']] = qase_user['id']
                    flag = True
                    self.logger.log(f"[Users] User {testrail_user['email']} found in Qase as {qase_user['email']}")
                    break
            if not flag:
                # Not found, using default user
                self.mappings.users[testrail_user['id']] = self.config.get('users.default')
                self.logger.log(f"[Users] User {testrail_user['email']} not found in Qase, using default user.")
            self.logger.print_status('Building users map', i, total)

    async def create_root_group(self):
        if self.config.get('groups.name') is not None:
            group_name = self.config.get('groups.name')
        else:
            group_name = 'TestRail Migration'
        self.logger.log(f"[Users] Creating group {group_name}")
        self.mappings.group_id = await self.pools.qs(self.scim.create_group, group_name)
        for id in self.active_ids:
            self.logger.log(f"[Users] Adding user {id} to group {group_name}")
            self.scim.add_user_to_group(self.mappings.group_id, id)

    async def create_users(self):
        self.logger.log("[Users] Loading users from Qase using SCIM")
        qase_users = await self.pools.qs_gen_all(self.scim.get_all_users)

        async with asyncio.TaskGroup() as tg:
            for testrail_user in self.testrail_users:
                flag = False
                for qase_user in qase_users:
                    if testrail_user['email'].lower() == qase_user['userName'].lower():
                        self.logger.log("[Users] User found in Qase using SCIM, skipping creation.")
                        self.map[testrail_user['id']] = qase_user['id']
                        if testrail_user['is_active']:
                            self.active_ids.append(qase_user['id'])
                        flag = True
                if not flag:
                    # Not found, using default user
                    if testrail_user['is_active'] is False and not self.config.get('users.inactive'):
                        self.logger.log(f"[Users] User {testrail_user['email']} is not active, skipping creation.")
                        continue
                    try:
                        if self.config.get('users.create'):
                            tg.create_task(self.import_user(testrail_user))
                    except Exception as e:
                        self.logger.log(f"[Users] Failed to create user {testrail_user['email']}", 'error')
                        self.logger.log(f'{e}')
                        continue

    async def import_user(self, testrail_user):
        user_id = await self.create_user(testrail_user)
        self.map[testrail_user['id']] = user_id
        if testrail_user['is_active']:
            self.active_ids.append(user_id)

    async def get_testrail_users(self):
        self.logger.log("[Users] Getting users from TestRail")
        limit = 250
        offset = 0
        while True:
            users = await self.pools.tr(self.testrail.get_users, limit, offset)
            if 'users' in users and users['users'] is not None:
                users = users['users']

            self.testrail_users = self.testrail_users + users

            if len(users) < limit or len(users) > limit:
                break

            offset += limit
        self.logger.log(f"[Users] Found {len(self.testrail_users)} users in TestRail")

    async def create_user(self, testrail_user):
        # Function creates a new user in Qase
        self.logger.log(f"[Users] Creating user {testrail_user['email']} in Qase")
        parts = testrail_user['name'].split()
        if len(parts) == 2:
            first_name = parts[0]
            last_name = parts[1]
        else:
            first_name = testrail_user['name']
            last_name = ''

        user_id = await self.pools.qs(
            self.scim.create_user,
            testrail_user['email'],
            first_name,
            last_name,
            testrail_user['role'],
            testrail_user['is_active'],
        )
        self.logger.log(f"[Users] User {testrail_user['email']} created in Qase with id {user_id}")
        return user_id

    async def import_groups(self):
        self.logger.log("[Users] Importing groups from TestRail")
        groups = await self.pools.tr_gen_all(self.get_all_groups)
        self.logger.log(f"[Users] Found {len(groups)} groups in TestRail")

        async with asyncio.TaskGroup() as tg:
            for group in groups:
                tg.create_task(self.import_group(group))

    async def import_group(self, group):
        self.logger.log(f"[Users] Importing group {group['name']}")
        group_id = await self.pools.qs(self.scim.create_group, group['name'])

        async with asyncio.TaskGroup() as tg:
            for id in group['user_ids']:
                if id in self.map:
                    if self.map[id] in self.active_ids:
                        self.logger.log(f"[Users] Adding user {id} to group {group['name']}")
                        tg.create_task(self.pools.qs_task(self.scim.add_user_to_group, group_id, self.map[id]))
                    else:
                        self.logger.log(f"[Users] User {id} is not active, skipping adding to group {group['name']}")

    def get_all_groups(self, limit=250):
        self.logger.log("[Users] Loading all groups from TestRail")
        offset = 0
        while True:
            groups = self.testrail.get_groups(limit, offset)
            if 'groups' in groups and groups['groups'] is not None:
                groups = groups['groups']

            yield groups
            offset += limit
            if len(groups) < limit:
                break
