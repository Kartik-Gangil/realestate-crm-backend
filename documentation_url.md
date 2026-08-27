# Real Estate CRM API Integration Guide

Local base URL: `http://127.0.0.1:8000`. Protected endpoints require `Authorization: Token <token>`. Use JSON unless uploading a file, where `multipart/form-data` is required. `<slug>` is the organization slug. List pagination uses `page` and `page_size` (maximum 100) and returns `{count,next,previous,results}`.

## Authentication

| Method | URL | Access |
|---|---|---|
| POST | `/api/auth/register/` | Public |
| POST | `/api/auth/login/` | Public |
| POST | `/api/auth/logout/` | Token |
| GET | `/api/auth/me/` | Token |
| POST | `/api/auth/forgot-password/` | Public |
| POST | `/api/auth/reset-password/` | Public |
| POST | `/api/auth/change-password/` | Token |

`POST /api/auth/login/` body: `{ "email":"admin@example.com", "password":"..." }`. The response contains the token for all later calls.

## Platform and organization administration

Platform-only means Django superuser or `Platform Admin` group user.

| Method | URL | Access |
|---|---|---|
| GET, POST | `/api/platform/organizations/` | Platform |
| POST | `/api/platform/admins/` | Superuser |
| POST | `/api/platform/organizations/<slug>/access/` | Superuser |
| GET, POST | `/api/organizations/<slug>/members/` | Organization admin/platform |
| GET, PATCH | `/api/organizations/<slug>/members/<membership_id>/tab-permissions/` | Organization admin/platform |
| GET | `/api/organizations/<slug>/my-tab-permissions/` | Member |

Create organization body: `{ "name":"Acme", "slug":"acme", "organization_admin_email":"admin@example.com" }`. Add member body: `{ "email":"user@example.com", "role":"admin|manager|telecaller", "tab_permissions":["dashboard"] }`.

`GET /api/organizations/<slug>/my-tab-permissions/` is the frontend authorization payload. It returns the user's `role`, effective `tab_permissions`, and canonical `permissions`. A tab is enabled only when both the role has its required permission and the member's stored `tab_permissions` includes it. The current mapping is `dashboard -> dashboard.view`, `leads|assigned_leads|follow_ups -> leads.view`, and `members -> employees.view`. Platform admins receive all tabs and permissions.

For an organization-admin tab editor, use `GET /api/organizations/<slug>/members/<membership_id>/tab-permissions/`. It returns `selected_tab_permissions` (checkbox state), `role_allowed_tabs` (tabs the role permits), and `effective_tab_permissions` (what the member will actually see). Save checkbox changes with `PATCH` to the same URL using `{ "tab_permissions": ["dashboard", "leads"] }`.

## Settings & Administration

### Platform Settings

| Method | URL | Notes |
|---|---|---|
| GET | `/api/settings/overview/` | Database-backed dashboard aggregates. |
| GET | `/api/settings/organizations/?search=` | Organization picker. |
| GET | `/api/settings/system-info/` | Safe runtime/system information; no secrets. |
| GET | `/api/settings/audit-logs/?page=&page_size=&date_from=&date_to=&user=&organization=&module=&action=` | Immutable audit history. |
| GET, POST | `/api/settings/backups/` | POST needs `{ "confirmation":true }`; reports `unsupported` when no backup backend is configured. |
| POST | `/api/settings/maintenance/` | `{ "operation":"clear_cache|rebuild_search_index", "confirmation":true }`. |
| GET, POST | `/api/settings/health-check/` | Database, storage, cache and migration health. |

### Organization Settings

| Method | URL | Notes |
|---|---|---|
| GET, PATCH | `/api/organizations/<slug>/settings/general/` | `company_name`, `company_logo`, `date_format`, IANA `timezone`, ISO `currency`, `items_per_page` (1–100). |
| GET, POST | `/api/organizations/<slug>/settings/integrations/` | Create/list `email`, `sms`, `whatsapp`, `document_storage`. |
| PATCH | `/api/organizations/<slug>/settings/integrations/<integration_id>/` | Credentials/critical disable requires confirmation. |
| GET, POST | `/api/organizations/<slug>/settings/system-parameters/` | Typed parameter list/create. |
| PATCH, DELETE | `/api/organizations/<slug>/settings/system-parameters/<parameter_id>/` | Critical changes require confirmation. |
| GET | `/api/organizations/<slug>/settings/masters/` | All master data. |
| GET, POST | `/api/organizations/<slug>/settings/masters/<master_type>/` | One master type. |
| PATCH, DELETE | `/api/organizations/<slug>/settings/masters/<master_type>/<item_id>/` | Delete requires confirmation. |
| GET | `/api/organizations/<slug>/permissions/` | Permission catalogue grouped by module. |
| GET, POST | `/api/organizations/<slug>/role-mapping/` | List/change membership role mapping. |
| PATCH | `/api/organizations/<slug>/role-mapping/<membership_id>/` | `{ "role_id":1, "confirmation":true }`. |
| GET | `/api/organizations/<slug>/access-matrix/` | Role × module × action matrix. |

General settings example:

```json
{"company_name":"Acme Estates","timezone":"Asia/Kolkata","currency":"INR","date_format":"DD/MM/YYYY","items_per_page":25}
```

Integration example. `secrets` is write-only, Fernet encrypted with `INTEGRATION_ENCRYPTION_KEY`, and never returned/logged:

```json
{"integration_type":"sms","name":"Primary SMS","enabled":true,"configuration":{"sender_id":"ACME"},"secrets":{"api_key":"provider-secret"},"confirmation":true}
```

Parameter example (`data_type` is `string`, `integer`, `decimal`, `boolean`, or `json`):

```json
{"category":"business_rules","parameter_key":"lead-followup-days","parameter_name":"Lead follow-up days","value":3,"data_type":"integer","is_critical":true,"confirmation":true}
```

Missing confirmation returns HTTP `409`: `{ "code":"confirmation_required" }`.

## Employees, HR, roles and leaves

| Method | URL |
|---|---|
| GET, POST | `/api/organizations/<slug>/employees/` |
| GET, PATCH, PUT | `/api/organizations/<slug>/employees/<employee_id>/` |
| POST | `/api/organizations/<slug>/employees/<employee_id>/activate/`, `deactivate/`, `reset-password/` |
| GET | `/api/organizations/<slug>/employees/<employee_id>/activity-history/` |
| GET, POST | `/api/organizations/<slug>/departments/` |
| GET, PATCH | `/api/organizations/<slug>/departments/<department_id>/` |
| GET, POST | `/api/organizations/<slug>/roles/` |
| GET, PATCH, PUT, DELETE | `/api/organizations/<slug>/roles/<role_id>/` |
| GET | `/api/organizations/<slug>/permissions/` |
| GET, POST | `/api/organizations/<slug>/holidays/`, `attendance/`, `leaves/` |
| POST | `/api/organizations/<slug>/attendance/check-in/`, `check-out/` |
| GET, PATCH | `/api/organizations/<slug>/leaves/<leave_id>/` |
| POST | `/api/organizations/<slug>/leaves/<leave_id>/approve/`, `reject/`, `cancel/` |

Role body: `{ "name":"Sales Manager", "code":"sales-manager", "permission_ids":[1,2] }`. Role deletion requires `{ "confirmation":true }` and fails with `409` while memberships still use the role.

## Leads and Site Visits

All paths below use prefix `/api/organizations/<slug>/`.

| Method | Path |
|---|---|
| GET, POST | `leads/`, `leads/<lead_id>/follow-ups/`, `sitevisits/`, `reschedulevisit/` |
| POST | `leads/import/`, `leads/assign-round-robin/` |
| PATCH | `leads/bulk_reset/`, `leads/<lead_id>/assign/` |
| GET | `leads/assigned/`, `leads/dashboard/`, `leads/summary/`, `dashboard/`, `summary/` |
| GET, PATCH, PUT, DELETE | `leads/<lead_id>/` |
| GET | `sitevisits/upcoming/`, `today/`, `calendar/`, `analytics/`, `sitevisits/<site_visit_id>/history/`, `leads/<lead_id>/sitevisits/` |
| GET, PATCH, PUT | `sitevisits/<site_visit_id>/` |
| POST | `sitevisits/<site_visit_id>/reschedule/`, `cancel/`, `no-show/`, `outcome/` |

## Inventory, bookings, payments and legal workflow

All paths below use prefix `/api/organizations/<slug>/`.

| Method | Path |
|---|---|
| GET, POST | `inventory/blocks/`, `plots/`, `bookings/`, `bookings/<booking_id>/payments/`, `installments/`, `agreement/`, `registry/`, `possession/` |
| GET, PATCH | `inventory/blocks/<block_id>/`, `plots/<plot_id>/`, `installments/<installment_id>/`, `agreements/<agreement_id>/`, `registries/<registry_id>/`, `possessions/<possession_id>/` |
| POST | `inventory/plots/bulk-status/`, `plots/<plot_id>/status/`, `block/`, `hold/`, `release/`, `select/` |
| GET | `inventory/plots/<plot_id>/history/`, `bookings/`, `inventory/bookings/<booking_id>/`, `inventory/leads/<lead_id>/bookings/` |
| POST | `inventory/bookings/<booking_id>/confirm/`, `cancel/` |
| GET | `inventory/payments/`, `payments/<payment_id>/`, `installments/`, `agreements/`, `registries/`, `possessions/` |
| POST | `inventory/payments/<payment_id>/confirm/`, `fail/`, `refund/`, `installments/<installment_id>/allocate/` |
| POST | `inventory/agreements/<agreement_id>/ready/`, `sign/`, `cancel/` |
| POST | `inventory/registries/<registry_id>/schedule/`, `complete/`, `cancel/` |
| POST | `inventory/possessions/<possession_id>/schedule/`, `complete/`, `cancel/` |
| GET | `inventory/plot-inventory/`, `plot-inventory/<plot_id>/`, `plot-inventory/<plot_id>/availability/` |
| POST | `inventory/plot-inventory/<plot_id>/select/` |
| GET | `inventory/plot-selections/`, `plot-selections/<selection_id>/` |
| POST | `inventory/plot-selections/<selection_id>/confirm/`, `release/` |

## Documents

All paths below use prefix `/api/organizations/<slug>/`.

| Method | Path |
|---|---|
| GET, POST | `documents/`, `documents/categories/`, `customers/<customer_id>/document-requirements/`, `employees/<employee_id>/documents/` |
| GET | `documents/<document_id>/`, `download/`, `history/`, `documents/pending-verification/`, `expiry-alerts/`, `customers/<customer_id>/documents/` |
| POST | `documents/<document_id>/under-verification/`, `verify/`, `reject/`, `archive/`, `employee-documents/<document_id>/archive/` |
| PATCH | `documents/categories/<category_id>/`, `customers/<customer_id>/document-requirements/<requirement_id>/` |
| GET | `employee-documents/<document_id>/`, `download/`, `history/` |

## Payment Management (organization scoped)

| Method | Path |
|---|---|
| GET, POST | `/api/organizations/<slug>/payments/` |
| GET | `/api/organizations/<slug>/payments/summary/` |
| GET | `/api/organizations/<slug>/payments/<payment_id>/` |
| POST | `/api/organizations/<slug>/payments/<payment_id>/confirm/`, `/receipt/`, `/refund/`, `/adjustment/` |
| POST | `/api/organizations/<slug>/payments/<payment_id>/refunds/<refund_id>/approve/` |
| GET | `/api/organizations/<slug>/customers/<customer_id>/payments/`, `/dues/`, `/payment-ledger/` |

Create payload: `{ "booking_allocations":[{"booking_id":1,"amount":"100.00","installment_id":null,"registry_charge_id":null}], "amount":"100.00", "payment_mode":"upi", "payment_date":"2026-05-15", "transaction_reference":"REF-1", "remarks":"Booking payment" }`. Allocation totals must equal the payment amount and are checked against locked outstanding balances. Confirmation creates an immutable receipt and status history. Refunds are requested first and become effective only after approval/completion.

## Registry Management (organization scoped)

| Method | Path |
|---|---|
| GET, POST | `/api/organizations/<slug>/registries/` |
| GET, PATCH | `/api/organizations/<slug>/registries/<registry_id>/` |
| POST | `/api/organizations/<slug>/registries/<registry_id>/status/` |
| GET | `/api/organizations/<slug>/registries/<registry_id>/history/` |

Registry creation resolves a confirmed booked `PlotBooking`, requires a signed Agreement, snapshots configured `registry_charge_type` master data, and never accepts customer/plot/organization values as authoritative. Status transitions are controlled; completion requires a registry date and a passing customer-document validation.

## Frontend integration reference — legacy inventory APIs

All requests require `Authorization: Bearer <access_token>` and use JSON (`Content-Type: application/json`). Replace `<slug>` with the organization slug. Organization, actor, status, IDs, and financial totals are server-controlled; foreign-organization IDs return 404. List endpoints use `{count,next,previous,results}` and accept `page`, `page_size`, and (where supported) `search`, `status`, `ordering`.

### Blocks

`GET /inventory/blocks/` lists blocks; `POST` creates one: `{ "name":"North Block", "code":"NORTH" }`.

`GET /inventory/blocks/<block_id>/` returns a block; `PATCH` accepts `name` and/or `code`.

Response: `{ "id":1, "name":"North Block", "code":"NORTH", "organization":{ "id":2,"name":"Acme","slug":"acme" }, "created_at":"...", "updated_at":"..." }`.

### Plots

`GET /inventory/plots/` supports `search`, `status`, `block`, `plot_type`, and `page`. `POST /inventory/plots/` payload:

```json
{"block":1,"plot_number":"A-101","size":"120.00","plot_type":"residential","rate_per_sq_unit":"2500.00","total_price":"300000.00","facing":"East","dimensions":"10x12","description":"Corner plot"}
```

`GET/PATCH /inventory/plots/<plot_id>/` accepts the same editable fields except `status` (status has a dedicated endpoint). Status operation payload: `POST /inventory/plots/<plot_id>/status/` with `{ "status":"booked", "reason":"Booking confirmed", "from_datetime":null, "to_datetime":null, "notes":"" }`.

Hold/block/release use `POST /inventory/plots/<plot_id>/{hold,block,release}/`. Hold/block accept `reason`, optional timezone-aware ISO-8601 `from_datetime`/`to_datetime`, and `notes`; release accepts `reason` and `notes`. `GET /inventory/plots/<plot_id>/history/` returns immutable status events.

### Bookings

`GET /inventory/bookings/` supports `search`, `status` (`pending|confirmed|cancelled`), `lead`, `plot`, and `block`. `POST` payload:

```json
{"lead_id":7,"plot_id":101,"site_visit_id":55,"notes":"Customer selected plot"}
```

`POST /inventory/plots/<plot_id>/bookings/` uses the same payload without `plot_id` (the URL supplies it). A successful create returns `{id,status,plot_status,lead,plot,site_visit,notes,created_by,created_at,updated_at}`. `GET /inventory/bookings/<booking_id>/` additionally returns `financial_summary`, `payments`, `installments`, `agreement`, `registry`, and `possession`.

`POST /inventory/bookings/<booking_id>/confirm/` has no body and transactionally confirms the booking after the existing customer-document gate. `POST .../cancel/` payload: `{ "reason":"Customer withdrew" }`. `GET /inventory/leads/<lead_id>/bookings/` lists that lead's bookings.

### Legacy booking payments

`GET /inventory/bookings/<booking_id>/payments/` lists payments. `POST` payload:

```json
{"amount":"150000.00","payment_method":"upi","payment_date":"2026-05-15","transaction_reference":"UPI123","notes":"Booking payment"}
```

`GET /inventory/payments/` supports `status` and `booking`; `GET /inventory/payments/<payment_id>/` returns payment, lead, plot, and refunds. `POST /inventory/payments/<payment_id>/confirm/` confirms transactionally; `POST .../fail/` marks a pending payment failed. `POST .../refund/` payload is `{ "amount":"1000.00", "reason":"Duplicate payment", "refund_date":"2026-05-16" }`. New management clients should use `/payments/` APIs documented above, where refunds require approval.

### Installments

`POST /inventory/bookings/<booking_id>/installments/` payload: `{ "installment_number":1,"title":"First installment","due_date":"2026-06-01","amount":"100000.00","notes":"" }`.

`GET /inventory/installments/` and `GET/PATCH /inventory/installments/<installment_id>/` support installment metadata (`title`, `due_date`, `amount`, `notes`); status cannot be edited directly. Allocate with `POST /inventory/installments/<installment_id>/allocate/`: `{ "payment_id":12,"amount":"50000.00" }`. Allocation cannot exceed either the payment or installment balance.

### Agreement and registry workflow

Create/read an agreement with `GET,POST /inventory/bookings/<booking_id>/agreement/`. POST payload: `{ "agreement_number":"AGR-001","agreement_date":"2026-05-01","document_reference":"stored-document-ref","notes":"" }`. Agreement transitions are bodyless `POST /inventory/agreements/<agreement_id>/{ready,sign,cancel}/`.

Create/read a registry with `GET,POST /inventory/bookings/<booking_id>/registry/`. POST payload: `{ "registry_number":"REG-001","registry_date":"2026-06-15","notes":"" }`. Creation requires a confirmed booking and signed agreement. Registry transitions are bodyless `POST /inventory/registries/<registry_id>/{schedule,complete,cancel}/`; completion additionally requires `registry_date` and valid required customer documents. `GET /inventory/registries/` and `GET/PATCH /inventory/registries/<registry_id>/` expose registry data.

### Possession

Create/read with `GET,POST /inventory/bookings/<booking_id>/possession/`. POST payload: `{ "possession_date":"2026-07-01","notes":"Handover scheduled" }`. A completed registry is required. Use bodyless `POST /inventory/possessions/<possession_id>/{schedule,complete,cancel}/` for transitions.

### Common errors

`400` contains field validation details, `401` means missing/invalid authentication, `403` means insufficient organization permission, and `404` means missing or foreign-organization resource. Never send `organization_id`, `created_by`, `status`, or generated IDs as authoritative values.

## Error responses

| HTTP status | Meaning |
|---|---|
| 400 | Validation error or invalid operation. |
| 401 | Missing/invalid token. |
| 403 | Authenticated but lacks platform, organization, or role permission. |
| 404 | Missing resource or cross-organization resource. |
| 409 | Confirmation required or role still has assigned memberships. |

The backend derives organization and actor from the URL/token. Do not send `organization_id`, audit fields, actor fields, or decrypted secrets as authoritative client data.
