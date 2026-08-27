# Current implementation snapshot — Settings, RBAC, API documentation (2026-08-27)

This section is the authoritative record of the Settings & Administration work completed so far. It supplements the historical implementation notes below.

## Implemented database changes

### `organizations.0007_organizationmembership_organization_role`

- Added nullable `OrganizationMembership.organization_role` (`PROTECT` FK to `OrganizationRole`).
- Added an idempotent data migration which:
  - creates the extended Permission catalogue;
  - ensures `admin`, `manager`, and `telecaller` roles for every existing organization;
  - assigns explicit baseline permission matrices;
  - maps all existing membership `role` strings to the matching canonical `organization_role`.
- The legacy string field `OrganizationMembership.role` remains for backward-compatible API responses and old consumers. It is no longer intended to be the RBAC source.
- New organizations and employee creation use `ensure_default_roles(organization)` so default canonical roles are provisioned idempotently.

### `system_settings.0001_initial`

Created the dedicated `system_settings` app and these models:

- `OrganizationSettings`: one-to-one organization configuration; company name/logo, date format, timezone, currency, and pagination size.
- `MasterData`: organization-scoped, controlled master metadata (`master_type`, code, name, color, description, active flag, sort order).
- `IntegrationConfiguration`: organization-scoped integration configuration, encrypted secret payload, safe status, timestamps and error text.
- `SystemParameter`: typed organization parameter with category, key, value, type, critical flag and activation state.
- `AuditLog`: append-only generalized audit record, optional organization and actor, module/action, timestamp, IP, sanitized details and target reference.
- `BackupRecord`: backup operation metadata. It does not expose filesystem paths or direct backup downloads.

Migrations were applied locally:

```text
organizations.0007_organizationmembership_organization_role
system_settings.0001_initial
```

## Authorization design and current behavior

### Platform access

`organizations.services.can_access_platform_settings(user)` is the centralized decision for platform Settings APIs.

- Django `is_superuser=True` users are Platform Admins.
- Users in the existing `Platform Admin` Django group are Platform Admins.
- Platform Admins have cross-organization administrative access through `get_organization_access()`.
- An organization role named `admin` is not a Platform Admin role.

### Organization RBAC

The intended authorization chain is:

```text
User
  -> OrganizationMembership
  -> OrganizationRole (organization_role)
  -> Permission[]
```

`organizations.services.has_permission(user, organization, permission_code)` loads the active membership and checks the permission from the canonical `organization_role` relation. Platform Admins automatically pass this check.

Permission catalogue codes include modules/actions such as:

```text
dashboard.view
leads.view / leads.add / leads.edit / leads.delete / leads.export
customers.view / customers.add / customers.edit / customers.delete / customers.export
plots.view / plots.add / plots.edit / plots.delete / plots.export
payments.*
registry.*
reports.view / reports.export
employees.*
documents.*
attendance.*
leave.*
settings.view / settings.edit
```

RBAC has been wired into selected existing management operations:

- lead management uses `leads.edit`;
- inventory/plot management uses `plots.edit`;
- employee management uses `employees.edit`;
- document management uses `documents.edit`;
- organization Settings uses `settings.view` / `settings.edit`.

### Important current limitation — sidebar tabs are separate

Sidebar tab visibility still derives from `OrganizationMembership.tab_permissions`, returned by:

```text
GET /api/organizations/<slug>/my-tab-permissions/
```

It does **not** currently derive from `OrganizationRole.permissions`. Therefore changing a role's `permission_ids` can change protected backend action authorization, but does not automatically add/remove sidebar UI tabs.

Current access systems are therefore:

```text
Sidebar visibility        -> OrganizationMembership.tab_permissions
Backend selected actions  -> OrganizationRole.permissions via has_permission()
```

To make sidebar navigation fully role-driven in a future change, map each tab to a permission, for example `leads -> leads.view`, `members -> employees.view`, `settings -> settings.view`, `inventory -> plots.view`, and derive `my-tab-permissions` from the role. Alternatively use an intersection of role-derived tabs and explicit `tab_permissions` for per-user restrictions.

### Important current limitation — legacy endpoint coverage

Permission enforcement is not yet comprehensive across every historical list/detail/action endpoint in leads, inventory, documents, and HR. Existing membership/access-scope checks still protect those routes, but role permission changes do not yet govern every legacy route. UI hiding is not a security control; unconnected backend routes must be migrated to `has_permission()` incrementally.

## Role and permission APIs

### Existing role CRUD

```text
GET, POST                     /api/organizations/<slug>/roles/
GET, PATCH, PUT, DELETE       /api/organizations/<slug>/roles/<role_id>/
```

`GET` role response:

```json
{
  "id": 5,
  "name": "Sales Manager",
  "code": "sales-manager",
  "is_system": false,
  "permissions": ["leads.view", "leads.add", "leads.edit"]
}
```

`PATCH`/`PUT` accepts only the fields it receives:

```json
{
  "name": "Senior Sales Manager",
  "code": "senior-sales-manager",
  "permission_ids": [1, 2, 3]
}
```

`permission_ids` replaces the full role permission set; it does not append. It uses IDs retrieved from the permissions API. Role deletion requires `confirmation: true` and returns HTTP 409 if any membership uses that canonical role.

### Permissions and mapping

```text
GET                           /api/organizations/<slug>/permissions/
GET, POST                     /api/organizations/<slug>/role-mapping/
PATCH                         /api/organizations/<slug>/role-mapping/<membership_id>/
GET                           /api/organizations/<slug>/access-matrix/
```

The effective permissions of a user are changed in two steps:

1. Update the role `permission_ids`.
2. Assign the role to the user's `OrganizationMembership` with `{ "role_id": <id>, "confirmation": true }`.

Role mapping GET response shape:

```json
{
  "id": 12,
  "user": {"id": 7, "email": "employee@example.com"},
  "role": {"id": 5, "code": "sales-manager"}
}
```

Direct per-user permission overrides do not exist. Use a custom role with the required permissions, then map that role to the membership.

## Settings APIs created

Platform Admin/Superuser only:

```text
GET                           /api/settings/overview/
GET                           /api/settings/organizations/?search=
GET                           /api/settings/system-info/
GET                           /api/settings/audit-logs/?page=&page_size=&date_from=&date_to=&user=&organization=&module=&action=
GET, POST                     /api/settings/backups/
POST                          /api/settings/maintenance/
GET, POST                     /api/settings/health-check/
```

Organization-scoped Settings routes (`settings.view` for read and `settings.edit` for mutations, unless platform admin):

```text
GET, PATCH                    /api/organizations/<slug>/settings/general/
GET, POST                     /api/organizations/<slug>/settings/integrations/
PATCH                         /api/organizations/<slug>/settings/integrations/<integration_id>/
GET, POST                     /api/organizations/<slug>/settings/system-parameters/
PATCH, DELETE                 /api/organizations/<slug>/settings/system-parameters/<parameter_id>/
GET                           /api/organizations/<slug>/settings/masters/
GET, POST                     /api/organizations/<slug>/settings/masters/<master_type>/
PATCH, DELETE                 /api/organizations/<slug>/settings/masters/<master_type>/<item_id>/
GET                           /api/organizations/<slug>/permissions/
GET, POST                     /api/organizations/<slug>/role-mapping/
PATCH                         /api/organizations/<slug>/role-mapping/<membership_id>/
GET                           /api/organizations/<slug>/access-matrix/
```

### Security behavior implemented

- Every Settings route requires token authentication.
- Platform routes reject normal organization users with HTTP 403.
- Organization objects are always resolved from the URL organization slug, never request `organization_id`.
- Integration `secrets` is write-only and encrypted with Fernet using `INTEGRATION_ENCRYPTION_KEY`; missing/invalid keys return a validation error rather than creating an unreadable secret.
- Audit sanitization redacts password, token, API key, secret, authorization and encryption-key style fields.
- Audit IP capture uses `REMOTE_ADDR`; proxy headers are intentionally not trusted without a configured trusted-proxy policy.
- Critical parameters, integration secret changes/disabling, role mapping, master deletion, backup, and maintenance require `confirmation: true`; absence returns `409` and `confirmation_required`.
- Backup is deliberately honest: no configured backend produces an `unsupported` `BackupRecord`, not a false success.
- Search-index rebuild returns `unsupported` because no index service exists. Cache clear only reports completion when the configured cache supports it.

## Documentation created

`documentation_url.md` was rewritten as a frontend integration guide. It includes all mounted API URL groups: authentication, platform/organization administration, Settings, employees/HR, leads/site visits, inventory/bookings/legal workflow, documents, sample settings payloads, pagination, authentication and errors.

## Files added or materially changed

```text
config/settings.py
config/urls.py
.env.example
documentation_url.md
organizations/models.py
organizations/services.py
organizations/views.py
organizations/serializers.py
organizations/employee_views.py
organizations/hr_views.py
organizations/migrations/0007_organizationmembership_organization_role.py
system_settings/__init__.py
system_settings/apps.py
system_settings/models.py
system_settings/services.py
system_settings/serializers.py
system_settings/views.py
system_settings/urls.py
system_settings/organization_urls.py
system_settings/permissions.py
system_settings/audit.py
system_settings/integrations.py
system_settings/maintenance.py
system_settings/admin.py
system_settings/tests.py
system_settings/migrations/0001_initial.py
```

## Verification completed

```text
python manage.py migrate                                      -> applied settings/RBAC migrations
python manage.py check                                        -> no issues
python manage.py makemigrations --check --dry-run             -> no changes detected
python manage.py test system_settings                         -> 6 passed
python manage.py test organizations.tests_employees documents.tests -> 10 passed
```

The Settings test coverage verifies platform access versus organization admin denial, general settings update and isolation, missing encryption-key safety, secret encryption/no response-or-audit leakage, critical parameter confirmation, and canonical role permission resolution.

# Plot Inventory Management Memory

This document records the Plot Inventory Management implementation completed in this Django CRM through Phase 3. Phase 4 and later integrations have not been implemented.

## Existing CRM inspected

- Django project: `config`
- Existing applications: `users`, `organizations`, `leads`
- Authentication: Django user model with DRF token authentication
- Tenant model: `organizations.Organization`
- Membership model: `organizations.OrganizationMembership`
- Roles currently defined by the CRM:
  - `admin`
  - `manager`
  - `telecaller`
- Organization access helper: `organizations.services.get_organization_access(user, slug)`
- Platform access: superusers and explicitly authorized Platform Admin users
- Existing API style: function-based Django REST Framework views using `@api_view`, `@permission_classes`, and `Response`
- Existing audit conventions: `created_at`, `updated_at`, and user foreign keys where applicable
- Existing pagination convention: `page`, `page_size`, maximum page size 100
- No existing relational Project/Site, Block, Property, Plot, or Land model was found. The existing `Sitevisit.site` field is free text and was not suitable for inventory ownership.

## Inventory app

Created and registered the dedicated `inventory` Django app:

```text
inventory/
    admin.py
    apps.py
    models.py
    serializers.py
    services.py
    tests.py
    tests_api.py
    tests_phase3.py
    urls.py
    migrations/
        0001_initial.py
        0002_plothold_plotstatushistory.py
        __init__.py
```

`inventory` is included in `config/settings.py` and its URLs are included beneath:

```text
/api/organizations/<organization_slug>/
```

## Phase 1 domain models

### Project

An organization-owned physical development/site entity required for the inventory hierarchy.

Fields:

- `organization`
- `name`
- `code`
- `created_at`
- `updated_at`

Constraint:

- Project code is unique within an organization.

### Block

Represents a block within a Project.

Fields:

- `organization`
- `project`
- `name`
- `code`
- `created_at`
- `updated_at`

Constraints and validation:

- Block code is unique within organization + project.
- Block organization must match Project organization.

### Plot

Represents physical plot inventory.

Fields:

- `organization`
- `project`
- `block`
- `plot_number`
- `size` — DecimalField, 2 decimal places
- `plot_type`
- `rate_per_sq_unit` — nullable DecimalField
- `total_price` — nullable DecimalField
- `facing`
- `dimensions`
- `status`
- `description`
- `created_by`
- `created_at`
- `updated_at`

Plot types:

- `residential`
- `commercial`
- `other`

Plot statuses:

- `available`
- `blocked`
- `hold`
- `booked`
- `sold`
- `cancelled`
- `under_construction`

The default status is `available`.

Plot constraints and model validation:

- Plot number is unique within organization + project + block.
- Size must be positive.
- Rate, when supplied, must be positive.
- Total price, when supplied, must be positive.
- Project organization must match Plot organization.
- Block organization must match Plot organization.
- Block must belong to the selected Project.

## Phase 2 APIs

All Phase 2 endpoints use `get_organization_access()` and scope querysets to `access.organization`.

### Plot list and create

```text
GET  /api/organizations/<organization_slug>/inventory/plots/
POST /api/organizations/<organization_slug>/inventory/plots/
```

List features:

- Database-backed pagination using `page` and `page_size`
- `count`, `next`, `previous`, and `results` response format
- Search across:
  - plot number
  - block name
  - block code
  - project name
  - project code
- Filters:
  - `project`
  - `block`
  - `status`
  - `plot_type`
- Multiple filters can be combined.
- Invalid filter IDs and choice values return validation errors.
- Cross-organization Project and Block filters are rejected.
- `select_related()` is used for organization, Project, Block, and creator.

Create behavior:

- Organization is always taken from URL access, never request data.
- `created_by` is always set to the authenticated request user.
- Project/Block organization and relationship consistency is validated.
- Status is not writable through create and defaults to `available`.
- Status, organization, creator, and ID impersonation fields are rejected.

### Plot detail and update

```text
GET   /api/organizations/<organization_slug>/inventory/plots/<plot_id>/
PATCH /api/organizations/<organization_slug>/inventory/plots/<plot_id>/
```

Detail response includes organization, Project, Block, plot metadata, creator, and timestamps.

Update behavior:

- Plot lookup is organization-scoped before retrieval.
- Normal metadata can be updated.
- Project/Block changes are checked for organization and hierarchy consistency.
- `organization`, `created_by`, and `id` cannot be changed.
- `status` is explicitly rejected; status changes use Phase 3 operations.
- Duplicate plot numbers are rejected through model validation and database constraints.

## Phase 3 status lifecycle

Centralized transition map in `inventory/services.py`:

```text
AVAILABLE -> BLOCKED, HOLD, BOOKED, UNDER_CONSTRUCTION
BLOCKED -> AVAILABLE, HOLD
HOLD -> AVAILABLE, BOOKED
BOOKED -> SOLD, CANCELLED
SOLD -> CANCELLED
CANCELLED -> AVAILABLE
UNDER_CONSTRUCTION -> AVAILABLE, BLOCKED, HOLD, BOOKED
```

Invalid transitions and same-status transitions are rejected. No history record is created for a rejected or no-op transition.

Reasons are required when changing to:

- `blocked`
- `hold`
- `cancelled`

## Phase 3 models

### PlotStatusHistory

Immutable status transition audit record.

Fields:

- `plot`
- `old_status`
- `new_status`
- `reason`
- `changed_by`
- `changed_at`

History records are ordered newest first and indexed by Plot plus descending change time. The model prevents normal updates to existing history records. Django admin is read-only for this model.

### PlotHold

Retains Block/Hold business events rather than storing only the current Plot status.

Fields:

- `plot`
- `action_type` — `block` or `hold`
- `reason`
- `from_datetime`
- `to_datetime`
- `notes`
- `created_by`
- `created_at`
- `released_at`

Rules:

- `to_datetime` must be later than `from_datetime` when both are supplied.
- Active records are retained until released.
- Release sets `released_at`; records are never deleted.
- Plot/time-range indexes support active-record and overlap queries.
- Overlapping active timed Block/Hold records are rejected inside the transaction.

## Phase 3 service layer

Implemented in `inventory/services.py`:

- `validate_status_transition(old_status, new_status)`
- `change_plot_status(...)`
- `block_plot(...)`
- `hold_plot(...)`
- `release_plot(...)`
- `bulk_change_plot_status(...)`

All status-changing API paths use the same transition logic. The core service:

1. Opens `transaction.atomic()`.
2. Locks the Plot with `select_for_update()`.
3. Revalidates the current status and requested transition.
4. Validates reason and Block/Hold time ranges.
5. Closes prior active temporary records when leaving Blocked/Hold.
6. Creates a new PlotHold record when entering Blocked/Hold.
7. Updates Plot status and `updated_at`.
8. Creates PlotStatusHistory.
9. Commits all changes atomically.

Bulk status changes lock all selected plots in deterministic primary-key order and are all-or-nothing. Every changed Plot receives its own history record.

## Phase 3 APIs

### Generic status operation

```text
POST /api/organizations/<organization_slug>/inventory/plots/<plot_id>/status/
```

Request example:

```json
{
  "status": "blocked",
  "reason": "Customer requested temporary block",
  "from_datetime": "2026-08-23T10:00:00+05:30",
  "to_datetime": "2026-08-25T18:00:00+05:30",
  "notes": "Awaiting confirmation"
}
```

### Dedicated operations

```text
POST /api/organizations/<organization_slug>/inventory/plots/<plot_id>/block/
POST /api/organizations/<organization_slug>/inventory/plots/<plot_id>/hold/
POST /api/organizations/<organization_slug>/inventory/plots/<plot_id>/release/
```

Block and Hold call the shared `change_plot_status()` service. Release only allows Blocked or Held plots and transitions them to Available.

### Status history

```text
GET /api/organizations/<organization_slug>/inventory/plots/<plot_id>/history/
```

History is returned newest first with pagination and `select_related("changed_by")`.

### Bulk status

```text
POST /api/organizations/<organization_slug>/inventory/plots/bulk-status/
```

Request example:

```json
{
  "plot_ids": [1, 2, 3],
  "status": "blocked",
  "reason": "Temporary project hold"
}
```

Response includes:

- `updated`
- updated Plot representations

Bulk requests reject empty/duplicate IDs, foreign-organization IDs, invalid statuses, missing reasons, and any invalid individual transition. No partial update occurs.

## Permissions and organization isolation

Read operations are available to authenticated members with organization access.

Write operations require:

- organization admin
- manager
- authorized platform access

Telecallers can view inventory but cannot perform status, Block, Hold, Release, or bulk operations.

Every operation uses `access.organization` as the source of truth. Organization IDs from request bodies are not trusted. Cross-organization plots are hidden as not found for object operations.

## Admin

Registered and optimized admin classes exist for:

- Project
- Block
- Plot
- PlotStatusHistory — read-only
- PlotHold

Foreign keys shown in admin lists use `select_related()`.

## Migrations

Applied migrations:

- `inventory.0001_initial`
- `inventory.0002_plothold_plotstatushistory`

No unrelated app migrations were changed, and the existing database was not reset.

## Tests

Phase 1 model tests cover creation, defaults, relationships, uniqueness, organization consistency, and numeric validation.

Phase 2 API tests cover list/create/detail/update, pagination, search, filters, validation, organization isolation, protected fields, and query-safe relationships.

Phase 3 tests cover:

- every allowed status transition
- invalid and same-status transitions
- required reasons
- history creation and immutability
- Block, Hold, and Release
- hold ranges and overlap behavior
- bulk success and rollback
- per-plot bulk history
- organization isolation
- read-only role permissions

Verification completed with the project virtual environment:

```text
python manage.py migrate                         -> inventory migration applied
python manage.py check                           -> no issues
python manage.py makemigrations --check --dry-run -> no changes detected
python manage.py showmigrations inventory        -> 0001 and 0002 applied
python manage.py test inventory.tests_phase3    -> 9 tests passed
```

The existing Phase 1 and Phase 2 inventory tests also passed after the Phase 3 changes.

## Explicitly not implemented

The following remain outside the completed scope:

- Booking integration
- Payment integration
- Site Visit integration
- Plot selection
- Registry integration
- Plot map/layout
- Analytics
- Reports
- Notifications, SMS, and email
- Phase 4 or later functionality

---

# Documents & Manual eKYC Management (implemented 2026-08-25)

## Important repository adaptation

The CRM has no separate `Customer` model. `leads.Lead` is the canonical customer entity and `PlotBooking.lead` is the booking customer relationship. The documents app therefore stores customer documents and requirements against `leads.Lead`, while retaining the user-facing/API term `customer`.

Inventory was inspected and already uses the required hierarchy:

```text
Organization -> Block -> Plot
```

`inventory.0006_remove_project_unique_inventory_project_code_and_more` has already removed the `Project` model and production inventory code has no Project dependency. Some legacy inventory test modules still import the removed model and need independent test cleanup.

## Application and models

Created the `documents` Django app and registered it in `INSTALLED_APPS`.

- `DocumentCategory`: organization-scoped reusable category, unique `organization + code`, active/inactive state.
- `CustomerDocumentRequirement`: Lead/customer-level category requirement, unique `organization + customer + category`; has mandatory and active flags.
- `CustomerDocument`: storage-backed, versioned document. Only one active version is permitted for an `organization + customer + category` tuple through a conditional unique constraint.
- `CustomerDocumentVerificationHistory`: append-only immutable status-change/audit records.

Migration added and applied:

- `documents.0001_initial`

## Storage and file security

`CustomerDocument.file` is a Django `FileField` with a callable storage-neutral upload path. It stores documents via the configured Django storage backend, currently `MEDIA_ROOT`, so S3 can later be enabled through Django storage settings without changing document services.

Settings added:

- `MEDIA_URL = '/media/'`
- `MEDIA_ROOT = BASE_DIR / 'media'`
- `DOCUMENT_MAX_UPLOAD_SIZE = 10 * 1024 * 1024`
- `DOCUMENT_EXPIRY_WARNING_DAYS = 30`

Uploads accept validated PDF/JPG/JPEG/PNG MIME types and file signatures, enforce the configurable maximum size, and generate sanitized unique file names. Downloads use an authenticated organization-scoped endpoint rather than exposing storage paths.

## Services and versioning

`documents.services` centralizes:

- `upload_customer_document`
- `archive_customer_document`
- `put_document_under_verification`
- `verify_customer_document`
- `reject_customer_document`
- `get_customer_document_summary`
- `validate_customer_documents_for_booking`

Uploading a replacement locks current records, archives the prior active version, calculates the next version, and creates the new document as active and `uploaded`. Documents are never physically deleted. Verification transitions are controlled centrally:

```text
uploaded -> under_verification -> verified
                              -> rejected
```

Rejection requires a reason. Verification actions and upload events create immutable history records. Mandatory-document validation evaluates only the active/latest version, including expiry dates.

## APIs

Mounted under `/api/organizations/<organization_slug>/`:

- `documents/` — GET list/search/filter/paginate and multipart POST upload
- `documents/<id>/`, `download/`, `history/`
- `documents/<id>/under-verification/`, `verify/`, `reject/`, `archive/`
- `documents/categories/` and `documents/categories/<id>/`
- `documents/pending-verification/`
- `documents/expiry-alerts/`
- `customers/<customer_id>/documents/`
- `customers/<customer_id>/document-requirements/` and requirement detail

Management/configuration and verification actions use existing admin/manager/platform access conventions. All document, category, requirement, customer, history, and download queries are organization scoped.

## Booking confirmation gate

`inventory.services.confirm_plot_booking` now calls `validate_customer_documents_for_booking` inside its existing transaction after locking the booking/plot. The validation service locks active requirements and active documents to avoid a stale-document race.

Booking confirmation is blocked if any active mandatory category is missing, pending, rejected, expired, or not verified. The API response has:

```json
{
  "detail": "Customer documents are incomplete.",
  "document_validation": {
    "allowed": false,
    "missing": [],
    "pending": [],
    "rejected": [],
    "expired": []
  }
}
```

## Admin and tests

Registered optimized admin views for categories, requirements, documents, and read-only verification history.

Added `documents.tests` coverage for:

- replacement/version archiving and latest-active authority
- valid and expired mandatory documents
- booking confirmation blocked when a required document is missing

Verification completed:

```text
python manage.py migrate                         -> no pending migrations
python manage.py check                           -> no issues
python manage.py makemigrations --check --dry-run -> no changes detected
python manage.py test documents                  -> 3 tests passed
```

## Employee Management Phase 1 (2026-08-26)

### Architectural decision

The existing backend had no separate Employee, Department, or generic activity model. The existing `organizations.OrganizationMembership` already represented an organization-specific team member and was referenced by leads/site visits for assignment. Employee Management therefore extends `OrganizationMembership` instead of introducing a parallel Employee model.

This preserves the existing relationship chain:

```text
User (global authentication account)
  -> OrganizationMembership (organization-specific employee/access record)
  -> Organization
```

Employee activation/deactivation is membership-level. Setting `OrganizationMembership.is_active=False` removes access to that organization through `get_organization_access()`, but does not set the global Django `User.is_active=False`; this avoids locking a user out of other organizations to which they belong.

### Organization model changes

`organizations.Organization` gained `employee_sequence`, a server-side counter used for organization-scoped employee IDs. New IDs are generated inside an atomic transaction while locking the organization row. Legacy IDs are skipped if they already exist.

`organizations.OrganizationMembership` gained organization-specific employee fields:

- `employee_id` (nullable for legacy memberships, unique per organization when present)
- organization-local `first_name` and `last_name` (fallback to the global User name for legacy records)
- `profile_photo` stored through Django's configured media storage
- `mobile_number`, `address`
- `date_of_birth`, `gender`
- `department`, `designation`, `reporting_manager`
- `date_of_joining`, `employment_type`, `salary`, `work_location`
- existing `role` and `is_active` remain the source of role/status behavior
- `access_scope`: `all`, `own`, `department`, or `custom`
- `custom_scope_memberships` and `custom_scope_departments` for custom visibility

Model validation enforces same-organization department and reporting manager relationships, prevents self-reporting, and rejects negative salary values.

### Department and audit models

Added `organizations.Department`:

- organization-scoped
- unique name within an organization
- description, active flag, created/updated timestamps

Added immutable `organizations.OrganizationActivity` for employee audit history:

- organization
- affected employee membership
- action and module
- JSON details
- authenticated performer
- server timestamp

Audit actions currently recorded include:

- `employee_created`
- `employee_updated`
- `employee_activated`
- `employee_deactivated`
- `role_assigned`
- `role_changed`
- `access_scope_changed`
- `employee_password_reset`

Activity rows cannot be updated after creation.

### Employee API implementation

Employee views and serializers are in `organizations/employee_views.py` and `organizations/employee_serializers.py`. They follow the existing function-based DRF style, TokenAuthentication, organization-slug routing, `get_organization_access()`, and the existing `{count, next, previous, results}` pagination shape.

Mounted under `/api/organizations/<organization_slug>/`:

- `GET/POST employees/` — list/search/filter/paginate or create
- `GET/PATCH/PUT employees/<id>/` — retrieve or update
- `POST employees/<id>/activate/`
- `POST employees/<id>/deactivate/`
- `POST employees/<id>/reset-password/`
- `GET employees/<id>/activity-history/`
- `GET/POST departments/`
- `GET/PATCH departments/<id>/`

Employee list supports:

- `page` and `page_size` (maximum 100)
- `search` across employee ID, local/global name, email, mobile, and designation
- `status=active|inactive`
- organization-validated `department`
- `designation`
- validated `ordering` using employee ID, name, designation, joining date, or joined date

Querysets use `select_related()` for user, department, and reporting manager. Detail serialization loads custom-scope relationships as needed.

Every object lookup is organization scoped. Department, manager, employee, and custom-scope department/employee IDs from another organization are rejected. Foreign objects are never accepted merely because their numeric ID exists.

### Authorization behavior

Existing organization roles are reused: `admin`, `manager`, and `telecaller`.

- Any authenticated organization member with permitted visibility can read employees.
- Admins, managers, platform admins, and superusers can create/update/activate/deactivate employees.
- Only organization admins, platform admins, and superusers can change roles or access scopes.
- Managers may create employees with the existing `telecaller` role and cannot assign custom scopes.
- Employee visibility respects the acting membership's access scope:
  - `all`: all organization memberships
  - `own`: only the acting membership
  - `department`: same department plus the acting membership
  - `custom`: selected individual memberships and selected departments plus the acting membership

No separate RBAC library or organization access system was introduced.

### Employee account creation and passwords

Creating an employee accepts an email and a write-only `temporary_password`. If the email does not belong to an existing Django user, a user account is created. If it belongs to an existing user without an organization membership, that account is linked to the new membership. Existing membership duplicates are rejected. Temporary passwords are never returned in API responses.

Added auth endpoints in `users/views.py` and `users/urls.py`:

- `POST /api/auth/forgot-password/` — generic response and secure time-limited email reset link
- `POST /api/auth/reset-password/` — accepts `uid`, `token`, and `new_password`
- `POST /api/auth/change-password/` — authenticated current-password change

Organization admins can issue a new temporary password through `employees/<id>/reset-password/`. Passwords are never written to activity details.

SMTP settings are loaded from the ignored root `.env` file. `.env.example` documents:

- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`
- `DEFAULT_FROM_EMAIL`
- `PASSWORD_RESET_FRONTEND_URL`

The project uses Django's SMTP email backend. No SMTP credentials are committed.

### Migrations and tests

Added:

- `organizations/migrations/0004_organizationactivity_organization_employee_sequence_and_more.py`
- `organizations/migrations/0005_organizationmembership_custom_scope_departments.py`

Added focused tests in `organizations/tests_employees.py` covering authentication, organization isolation, cross-organization relationship rejection, employee creation, generated IDs, search/filter/pagination, update, activation/deactivation, role restrictions, access scope visibility, activity attribution, forgot-password email dispatch, and password changes.

Verification performed:

```text
python manage.py check                           -> no issues
python manage.py makemigrations --check --dry-run -> no changes detected
PasswordResetApiTests                             -> 2 tests passed
EmployeeApiTests                                  -> employee tests passed in focused run
```

The full pre-existing suite is not clean: inventory test modules import a `Project` model that is absent from `inventory.models`, and one existing site-visit test also failed during the broad run. These failures are unrelated to Employee Management. The local database must apply the new migrations before normal login/API use:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

If migrations are not applied, login serialization can raise `sqlite3.OperationalError: no such column: organizations_organizationmembership.employee_id`, because the existing login endpoint serializes organization memberships using the expanded model.

---

## Employee Management Phase 2 — Partial implementation (2026-08-26)

> **Status: incomplete.** Performance Management was explicitly deferred by the user. Roles & Permissions migration, holiday-source import, focused Phase 2 tests, and final acceptance verification remain incomplete. Do not describe this as a completed Phase 2 implementation.

### User-confirmed rules captured

- Attendance lateness is based on each employee's configured `shift_start_time` and `shift_end_time`.
- Leave days exclude weekends and organization holidays.
- The official reference selected for the baseline holiday source is the Central Government gazetted calendar from the Government of India National Holiday Calendar: <https://www.india.gov.in/calendar>.
- Organization admins must also be able to create custom holidays.
- Performance metrics/status workflow was deferred; remind the user after the remaining work is complete.

### Models and migrations added

`organizations/migrations/0006_employee_phase2.py` was created and **applied**. It adds:

- `OrganizationMembership.shift_start_time` and `shift_end_time`
- `Permission` — reusable module/action permission catalogue
- `OrganizationRole` — organization-scoped role records with M2M permissions
- `OrganizationHoliday` — organization-scoped holiday date/name/source record
- `AttendanceRecord` — one daily record per employee, check-in/out, backend duration, and status
- `LeaveRequest` — Casual/Sick/Earned leave, calculated days, pending/approved/rejected/cancelled workflow fields

The migration seeds the permission catalogue and creates `admin`, `manager`, and `telecaller` role records for existing organizations. At this point, these role records are a compatibility/configuration layer only: the canonical migration away from the legacy `OrganizationMembership.role` string has **not** been completed.

`documents/migrations/0002_employee_phase2.py` was created and **applied**. It adds:

- `EmployeeDocumentCategory`
- `EmployeeDocument` — organization and membership scoped, storage-neutral `FileField`, version, active/archive status, expiry, uploader and metadata

The migration seeds the initial categories for every existing organization:

- Aadhar Card
- PAN Card
- Address Proof
- Offer Letter
- Experience Letter
- Salary Slip

### Files created/modified

Created:

- `organizations/hr_services.py`
- `organizations/hr_views.py`
- `organizations/migrations/0006_employee_phase2.py`
- `documents/migrations/0002_employee_phase2.py`

Modified:

- `organizations/models.py`
- `organizations/urls.py`
- `organizations/admin.py`
- `documents/models.py`
- `documents/services.py`
- `documents/views.py`
- `documents/urls.py`
- `documents/admin.py`

### Implemented API surface (partial)

Under `/api/organizations/<organization_slug>/`:

- `GET/POST roles/`
- `GET/PATCH/PUT/DELETE roles/<role_id>/`
- `GET permissions/`
- `GET/POST holidays/`
- `GET attendance/`
- `POST attendance/check-in/`
- `POST attendance/check-out/`
- `GET/POST leaves/`
- `GET/PATCH leaves/<leave_id>/`
- `POST leaves/<leave_id>/approve/`
- `POST leaves/<leave_id>/reject/`
- `POST leaves/<leave_id>/cancel/`
- `GET/POST employees/<employee_id>/documents/`
- `GET employee-documents/<document_id>/`
- `GET employee-documents/<document_id>/download/`
- `GET employee-documents/<document_id>/history/`
- `POST employee-documents/<document_id>/archive/`

### Services and behaviour added

- Attendance check-in/check-out state handling is transactional and calculates `total_hours` on the backend.
- Late status derives from `shift_start_time`; attendance is blocked if the employee has no configured shift start time.
- Check-out before check-in, check-out without check-in, and duplicate check-in/check-out attempts are rejected.
- Leave days are calculated server-side, excluding Saturday/Sunday plus `OrganizationHoliday` records.
- Leave starts pending; approve/reject is restricted in service logic to the reporting manager or an organization admin, and self-approval is rejected. Rejection requires a reason.
- Employee document uploads reuse the existing customer-document validation principles: PDF/JPG/PNG MIME and signature checks, configured maximum file size, storage-neutral `FileField`, atomic archival/version increment, authenticated organization-scoped download, and no physical deletion of historical versions.
- New operations create `OrganizationActivity` records for attendance, leave, role, and employee-document events. Passwords/tokens are not included in these details.

### Important migration incident resolved

After the model changes, login initially failed with:

```text
sqlite3.OperationalError: no such column: organizations_organizationmembership.shift_start_time
```

Cause: the new model fields existed in code before migration application, and login serializes organization memberships. Resolution: executed:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Applied successfully:

```text
organizations.0006_employee_phase2
documents.0002_employee_phase2
```

### Verification completed after partial work

```text
python manage.py check                            -> no issues
python manage.py makemigrations --check --dry-run -> no changes detected
python manage.py test organizations.tests_employees -> 7 tests passed
python manage.py test documents.tests               -> 3 tests passed
```

### Work still required

- Replace the legacy string `OrganizationMembership.role` with one canonical database role assignment through a backward-compatible data migration; update all role comparisons/query paths in organizations, users, leads, inventory, and documents.
- Connect database permissions to centralized authorization checks; current views still rely partly on legacy admin/manager/telecaller checks.
- Implement automatic Central Government holiday import/seeding and any future refresh process. The current `holidays/` endpoint supports only custom organization entries.
- Add management endpoints/admin workflow for employee document categories beyond migration-seeded defaults.
- Add the mandatory focused Phase 2 tests (roles, attendance, leave, employee documents, activities, isolation and authorization), then run full requested test coverage.
- Complete Performance Management only after confirming its review workflow/status rules with the user.

---

## Settings & Administration inspection and preparation (2026-08-26)

The Settings & Administration implementation request was inspected but not implemented. No Settings models, Settings dashboard, Settings URLs, role-mapping endpoints, access-matrix endpoints, master-data APIs, integrations APIs, system-parameter APIs, audit-log API, backup API, maintenance API, or critical-setting confirmation workflow were added.

### Repository findings

- The project remains a function-based Django REST Framework application with apps `users`, `organizations`, `leads`, `inventory`, and `documents`.
- Organization access continues to be provided by `organizations.services.get_organization_access(user, slug)`.
- `OrganizationRole` and `Permission` exist from the partial Employee Management Phase 2 work, but `OrganizationMembership.role` is still the legacy string field. The canonical database role-assignment migration remains incomplete.
- Existing role checks remain distributed across organizations, users, leads, inventory, and documents; centralized permission enforcement has not yet replaced them.
- `OrganizationActivity` is immutable, organization scoped, employee-linked, and currently has no IP-address field. It is the existing audit foundation but has not yet been extended for platform Settings audit records.
- No existing `OrganizationSettings`, integration configuration, typed system parameter, generic master-data, backup, cache-maintenance, or system-health service was found.
- Existing SMTP credentials are loaded from environment variables in `config/settings.py`; no encryption/key-management helper existed before this preparation.
- Existing Plot status choices and transition logic remain in `inventory`; no master-data change was made and no Plot status workflow was bypassed.

### Encrypted integration-secret preparation

The user selected encrypted database storage for integration secrets. The following dependency changes were made:

- Added `cryptography>=46.0.0` to `pyproject.toml`.
- Updated `uv.lock`.
- Ran `uv sync`, installing `cryptography==50.0.1` plus its dependencies (`cffi`, `pycparser`) in the project environment.

The intended implementation is authenticated Fernet encryption using an environment-provided `INTEGRATION_ENCRYPTION_KEY`. Secret fields must be write-only/update-only in API serializers and must never be returned, logged, or included in audit details. The encryption model/service itself has not yet been implemented.

### API documentation update

`documentation_url.md` was refreshed from the current URL configuration and now documents:

- Authentication endpoints.
- Platform and organization membership endpoints.
- Existing Employee Management and Department endpoints.
- Currently available partial Roles, Permissions, Holidays, Attendance, Leave, and Employee Document endpoints.
- Existing customer-document endpoints.
- Pagination, organization-isolation, server-controlled fields, and frontend integration notes.
- An explicit warning that Settings & Administration routes are not currently available.

### Verification during preparation

The dependency installation completed successfully with `uv sync`. No Settings migration or Settings tests were created or run. The existing backend checks and previously recorded Employee/Document focused tests remained the latest verification state.

### Settings work still required

- Complete canonical role migration and centralized permission service before using Roles & Permissions as the Settings authorization source.
- Add centralized Super Admin-only Settings access control while preserving organization-admin operational access boundaries.
- Implement organization settings, dashboard summaries, role mapping, access matrix, master metadata, encrypted integrations, typed parameters, extended audit logs, backup/maintenance service boundaries, critical mutation confirmation, migrations, and focused tests.
## Settings & Administration implementation (2026-08-26)

Implemented a dedicated `system_settings` Django app and applied:

- `organizations.0007_organizationmembership_organization_role`: adds canonical `OrganizationMembership.organization_role`, provisions the full permission catalogue, maps all existing legacy `admin`/`manager`/`telecaller` memberships, and assigns an explicit baseline permission matrix.
- `system_settings.0001_initial`: organization settings, master data, encrypted integration configuration, typed system parameters, immutable generalized audit log, and backup metadata.

Platform Settings authorization is centralized in `organizations.services.can_access_platform_settings`; superusers and existing `Platform Admin` group users are platform administrators. Organization-level access continues to use `get_organization_access`, with RBAC resolved through `has_permission(user, organization, code)` and membership access scopes remaining in force.

The Settings API includes overview, organization listing, general settings, permission catalogue, role mapping, access matrix, master data, integrations, typed parameters, audit logs, safe system info, health, maintenance, and honest unsupported backup/search-index boundaries. Integration secrets require `INTEGRATION_ENCRYPTION_KEY`, are Fernet encrypted, write-only, and audit-sanitized.

Verified after implementation:

```text
python manage.py migrate                                -> applied 0007 and settings 0001
python manage.py check                                  -> no issues
python manage.py makemigrations --check --dry-run       -> no changes detected
python manage.py test system_settings                   -> 6 passed
python manage.py test organizations.tests_employees documents.tests -> 10 passed
```
