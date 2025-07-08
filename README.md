# qase-testrail-migration

This script helps you to migrate your test cases from TestRail to Qase. It's written in Python 3.11 and uses [Qase API](https://developers.qase.io/reference/introduction-to-the-qase-api) and [TestRail API](https://support.testrail.com/hc/en-us/articles/7077083596436-Introduction-to-the-TestRail-API).

## How to use

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Create a new config file from the example or use template:

```json
{
    "qase": {
        "api_token": "<QASE_API_TOKEN>",
        "scim_token": "<QASE_SCIM_API_TOKEN>",
        "host": "<QASE_API_HOST|Default:qase.io>",
        "ssl": true,
        "enterprise": false
    },
    "testrail": {
        "connection": "api",
        "api": {
            "host": "<TESTRAIL_HOST>",
            "user": "<TESTRAIL_USER_EMAIL>",
            "password": "<TESTRAIL_USER_PASSWORD>"
        }
    },
    "projects": {
        "import": [],
        "status": "all|active|archived"
    },
    "tests": {
        "preserve_ids": true,
        "fields": [],
        "refs": {
            "enable": true,
            "url": "http://localhost:8899/"
        }
    },
    "runs": {
        "created_after": 1672524000
    },
    "users": {
        "default": 1,
        "create": true,
        "inactive": true
    },
    "groups": {
        "create": false,
        "name": "TestRail Migration"
    },
    "prefix": "local",
    "sync": false,
    "cache": true
}
```

Required fields to fill:

- `qase.host` - Qase host
- `qase.api` - API token from Qase
- `qase.scim` - SCIM token from Qase
- `qase.ssl` - If set to `true` migrator will use `https` instead of `http` in all requests
- `testrail.connection` - Type of connection to TestRail. Can be `api` or `db`
- `testrail.api.host` - URL of your TestRail instance
- `testrail.api.user` - Email of user in TestRail. This user should have *administrator* access rights
- `testrail.api.password` - Password of user in TestRail
- `projects.import` - List of projects to migrate. You can specify only name of project. Example: `["Project 1", "Project 2"]`
- `projects.status` - Status of projects to migrate. Can be `all`, `active` or `inactive`. 
- `users.default` - ID of user in Qase. This user will be used as author of all test cases if migrator unable to match user from TestRail to Qase
- `users.create` - If set to `true` migrator will create new users in Qase if it unable to match user from TestRail to Qase. *SCIM API token is required for this option.*
- `users.inactive` - If set to `true` migrator will migrate all users from TestRail to Qase. *SCIM API token is required for this option.*
- `groups.create` - If set to `true` migrator will create new groups in Qase if it unable to match group from TestRail to Qase. *SCIM API token is required for this option.*
- `groups.name` - Name of group in Qase where new users will be added. *SCIM API token is required for this option.*
- `runs.created_after` - Unix timestamp. Migrator will migrate only runs created after this date. *Optional*
- `tests.preserve_ids` - If set to `true` migrator will try to preserve test case IDs from TestRail. *Optional*
- `tests.fields` - List of fields to migrate. If empty, migrator will migrate all fields. *Optional*
- `tests.refs.enable` - If set to `true` migrator will add references to TestRail test cases. *Optional*
- `tests.refs.url` - URL of TestRail instance. *Optional*

### 3. Prepare system fields

Right now, there is no option to modify system fields in Qase through the API. If you want to migrate system fields values (like test result statuses or priority), you should add these values manually in Qase before migration. That can be done [here](https://app.qase.io/workspace/fields).

### 4. Run

```bash
python start.py
```
