# Real Estate CRM Backend

## Run locally

```powershell
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

## Authentication

Register or log in with email and password, then include the returned token in API requests.

```http
Authorization: Token <token>
```

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/register/` | Register a user |
| `POST` | `/api/auth/login/` | Log in and obtain a token |
| `POST` | `/api/auth/logout/` | Invalidate the current token |
| `GET` | `/api/auth/me/` | Current user |

## Organizations and access

Users may belong to multiple organizations. Every lead and follow-up call is organization-owned.

- `platform_superadmin`: Django user with `is_superuser=True`; has access to every organization.
- `platform_admin`: Must be promoted by a platform superadmin and explicitly granted organization access.
- `admin`: Full access to leads and organization members in their organization.
- `manager`: Full access to leads in their organization.
- `telecaller`: Sees only leads assigned to their membership and can log follow-up calls for them.

| Method | Endpoint | Access |
| --- | --- | --- |
| `POST` | `/api/platform/admins/` | Superadmin promotes a user using `{ "email": "..." }` |
| `GET/POST` | `/api/platform/organizations/` | Platform admin/superadmin lists or creates organizations |
| `POST` | `/api/platform/organizations/<slug>/access/` | Superadmin grants a platform admin explicit access |
| `GET/POST` | `/api/organizations/<slug>/members/` | Organization admin manages memberships |

Create an organization with an existing user's email as the initial organization admin:

```json
{
  "name": "Acme Realty",
  "slug": "acme-realty",
  "organization_admin_email": "admin@acmerealty.com"
}
```

## Tenant-scoped leads

All lead APIs require the organization slug in the path:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET/POST` | `/api/organizations/<slug>/leads/` | List/create leads |
| `GET/PATCH/PUT/DELETE` | `/api/organizations/<slug>/leads/<id>/` | Retrieve/manage one lead |
| `GET/POST` | `/api/organizations/<slug>/leads/<id>/follow-ups/` | List/log separate follow-up calls |
| `GET` | `/api/organizations/<slug>/dashboard/` | Lead counts and latest call records |
| `GET` | `/api/organizations/<slug>/summary/` | Lead totals grouped by status |

Lead sources are limited to `facebook`, `instagram`, and `website`. Required create fields are `first_name`, `phone`, and `source`. Phone numbers are intentionally not unique.

To assign a lead, send an active organization membership ID:

```json
{
  "first_name": "Mayank",
  "phone": "+918882364687",
  "source": "facebook",
  "assigned_membership": 12
}
```

Follow-up notes remain separate from the lead:

```json
{
  "note": "Customer asked for a callback tomorrow.",
  "outcome": "callback"
}
```

Valid outcomes are `connected`, `no_answer`, `busy`, `callback`, `not_interested`, and `invalid_number`.