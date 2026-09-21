# Expense API URL Documentation

## Base URL and authentication

All Expense routes require token authentication:

use the already created api instance to call the backend endpoints



Primary base URL:

```text
/api/
```

Versioned aliases are also mounted under:

```text
/api/v1/
```

Examples below use `/api/`.

All expense data is organization-scoped. Users who belong to multiple organizations should send an organization slug where the endpoint accepts it. Expense list, payment queues and reports use the existing `can_view` role scope.

Common paginated response:

```json
{
  "count": 25,
  "page": 1,
  "page_size": 25,
  "num_pages": 1,
  "next": null,
  "previous": null,
  "results": []
}
```

`page_size` defaults to `25` and is capped at `100`.

## Expense statuses and payment methods

Expense status values:

- `draft`
- `pending_approval`
- `changes_requested`
- `approved`
- `rejected`
- `cancelled`

Payment status values:

- `unpaid`
- `paid`

Payment method values:

- `cash`
- `card`
- `bank_transfer`
- `upi`

## 1. Categories

Category access requires the dynamic RBAC permission `expenses.manage_categories`. In the default setup this is available to organization admins. A custom Finance role can be granted this permission.

### List categories

```http
GET /api/categories/
```

Optional query parameters:

- `organization=<slug>` — filter categories by organization slug
- `is_active=true|false` — filter active/inactive categories

Response: HTTP `200`

```json
[
  {
    "id": 1,
    "organization": {
      "id": 1,
      "slug": "acme-realty",
      "name": "Acme Realty"
    },
    "name": "Travel",
    "description": "Travel and transport expenses",
    "is_active": true,
    "created_at": "2026-09-06T10:00:00+05:30",
    "updated_at": "2026-09-06T10:00:00+05:30"
  }
]
```

### Create category

```http
POST /api/categories/
Content-Type: application/json
```

Request body:

```json
{
  "organization": "acme-realty",
  "name": "Travel",
  "description": "Travel and transport expenses",
  "is_active": true
}
```

`organization` can be a slug or numeric organization ID. If the authenticated user belongs to only one organization, it may be omitted.

Response: HTTP `201`

```json
{
  "id": 1,
  "organization": {"id": 1, "slug": "acme-realty", "name": "Acme Realty"},
  "name": "Travel",
  "description": "Travel and transport expenses",
  "is_active": true,
  "created_at": "2026-09-06T10:00:00+05:30",
  "updated_at": "2026-09-06T10:00:00+05:30"
}
```

Category names must be unique inside an organization.

### Edit category

```http
PATCH /api/categories/<category_id>/
Content-Type: application/json
```

Accepted fields:

```json
{
  "name": "Office Supplies",
  "description": "Stationery and office consumables",
  "is_active": false
}
```

Response: HTTP `200`, with the updated category object.

There is no category `DELETE` endpoint. Deactivation is performed with `is_active=false`.

## 2. Expense list and CRUD

### List expenses

```http
GET /api/expenses/
```

Optional query parameters:

- `status=<status>`
- `payment_status=unpaid|paid`
- `category=<category_id>`
- `date_from=YYYY-MM-DD`
- `date_to=YYYY-MM-DD`
- `search=<text>` — searches description or numeric/human-readable expense ID
- `page=<number>`
- `page_size=<number>`

Deleted expenses are excluded. Results are filtered through `can_view`:

- own expenses for employees with own-view permission
- team expenses for users with `expenses.view_team`

Response: HTTP `200`, paginated. Each result contains the main expense fields:

```json
{
  "id": 12,
  "expense_id": "EXP012",
  "organization": {"id": 1, "slug": "acme-realty", "name": "Acme Realty"},
  "date": "2026-09-06",
  "category": {"id": 1, "name": "Travel", "is_active": true},
  "amount": "1250.00",
  "description": "Taxi to client meeting",
  "payment_method": "upi",
  "paid_by": {"id": 7, "email": "employee@example.com", "name": "Employee"},
  "submitted_by": {"id": 7, "email": "employee@example.com", "name": "Employee"},
  "receipt": "/media/expenses/acme-realty/EXP012/receipt.pdf",
  "notes": "Client visit",
  "project_reference": "Green Valley Phase 2",
  "is_advance": false,
  "status": "draft",
  "payment_status": "unpaid",
  "is_deleted": false,
  "created_at": "2026-09-06T10:00:00+05:30",
  "updated_at": "2026-09-06T10:00:00+05:30"
}
```

### Create expense

```http
POST /api/expenses/
Content-Type: application/json
```

Draft request:

```json
{
  "organization": "acme-realty",
  "category": 1,
  "date": "2026-09-06",
  "amount": "1250.00",
  "description": "Taxi to client meeting",
  "payment_method": "upi",
  "paid_by": 7,
  "notes": "Client visit",
  "project_reference": "Green Valley Phase 2",
  "is_advance": false,
  "action": "draft"
}
```

`submitted_by` defaults to the authenticated user. `paid_by` defaults to the authenticated user when omitted.

Submit-for-approval uses the same body with either:

```json
{"action": "submit"}
```

or:

```json
{"action": "submit-for-approval"}
```

Receipt rules:

- Drafts may be saved without a receipt.
- Submission requires `receipt`.
- Receipt must be JPG, JPEG, PNG or PDF.
- Maximum receipt size is 5 MB.

For file upload, use `multipart/form-data` and include the same fields plus the `receipt` file.

Submit response: HTTP `201`, with the expense detail object. Submission additionally creates:

- `Submitted` ApprovalStep with status `done`
- `Manager Review` ApprovalStep with status `pending`
- `Submitted` ActivityLog entry

### Get expense detail

```http
GET /api/expenses/<expense_id>/
```

Response: HTTP `200`. The detail response includes the normal expense fields plus:

```json
{
  "approval_steps": [
    {
      "id": 1,
      "step_name": "Submitted",
      "actor": {"id": 7, "email": "employee@example.com", "name": "Employee"},
      "status": "done",
      "acted_at": "2026-09-06T10:05:00+05:30",
      "comment": ""
    }
  ],
  "activity": [
    {
      "id": 1,
      "action": "Created",
      "actor": {"id": 7, "email": "employee@example.com", "name": "Employee"},
      "action_date": "2026-09-06T10:00:00+05:30",
      "snapshot": {"expense_id": "EXP012", "status": "draft"}
    }
  ]
}
```

### Edit expense

```http
PATCH /api/expenses/<expense_id>/
Content-Type: application/json
```

Editable fields:

- `date`
- `category`
- `amount`
- `description`
- `payment_method`
- `paid_by`
- `receipt`
- `notes`
- `project_reference`
- `is_advance`

Only the submitter can edit their own `draft` or `changes_requested` expense, subject to `expenses.edit_own`.

Approved expenses are read-only and return HTTP `400`.

### Cancel expense

```http
POST /api/expenses/<expense_id>/cancel/
```

No request body is required.

Response: HTTP `200`, with the updated expense. Cancellation sets:

```text
status = cancelled
is_deleted = true
```

It also creates a `Cancelled` ActivityLog entry. Approved-expense cancellation is currently blocked until the cancellation policy is confirmed.

There is no `DELETE /api/expenses/<id>/` endpoint.

## 3. Manager approval workflow

### Pending approval queue

```http
GET /api/expenses/pending-approval/
```

Optional query parameters:

- `page`
- `page_size`

Only assigned managers, Finance/custom approval roles, admins and platform admins can access actionable queue rows.

Response: HTTP `200`, paginated expense objects.

### Approve expense

```http
POST /api/expenses/<expense_id>/approve/
```

No request body is required.

Response: HTTP `200`, updated expense detail.

Effects:

- Current `Manager Review` step becomes `done`.
- Expense status becomes `approved`.
- A pending `Finance` step is created.
- `Approved` ActivityLog entry is created.

### Reject expense

```http
POST /api/expenses/<expense_id>/reject/
Content-Type: application/json
```

Request:

```json
{"comment": "Receipt is not readable."}
```

Comment is mandatory. Expense status becomes `rejected`, the active approval step becomes `rejected`, and a `Rejected` ActivityLog entry is created.

### Request changes

```http
POST /api/expenses/<expense_id>/request-changes/
Content-Type: application/json
```

Request:

```json
{"comment": "Please add the original receipt."}
```

Expense status becomes `changes_requested`. The submitter can edit and resubmit it. Resubmission resets the Manager Review step to `pending`.

## 4. Payments

### Unpaid payment queue

```http
GET /api/payments/unpaid/
```

Optional query parameters:

- `page`
- `page_size`

Returns approved, non-deleted expenses with `payment_status=unpaid` that are visible to the authenticated user.

Response: HTTP `200`, paginated results shaped as:

```json
{
  "expense": {"id": 12, "expense_id": "EXP012", "status": "approved", "payment_status": "unpaid"},
  "payment": null
}
```

### Paid payment queue

```http
GET /api/payments/paid/
```

Returns approved, non-deleted expenses with `payment_status=paid`. It uses the same pagination and response shape as the unpaid queue.

### Mark expense paid

```http
POST /api/expenses/<expense_id>/mark-paid/
Content-Type: application/json
```

Requires `expenses.process_payment`.

Request:

```json
{
  "payment_method": "upi",
  "payment_date": "2026-09-06",
  "reference_no": "UPI-12345",
  "paid_amount": "1250.00",
  "paid_by": 21
}
```

Only approved, unpaid expenses can be marked paid. `paid_by` must be an active member of the expense organization.

Response: HTTP `201`

```json
{
  "id": 4,
  "payment_status": "paid",
  "payment_method": "upi",
  "payment_date": "2026-09-06",
  "reference_no": "UPI-12345",
  "paid_by": {"id": 21, "email": "finance@example.com", "name": "Finance"},
  "paid_amount": "1250.00",
  "expense": {"id": 12, "expense_id": "EXP012", "status": "approved", "payment_status": "paid"}
}
```

The operation creates a `Payment`, updates the expense to `payment_status=paid`, and writes a `Paid` ActivityLog entry.

## 5. Reimbursements

### List reimbursements

```http
GET /api/reimbursements/
```

Optional query parameters:

- `status=pending|approved|rejected`
- `page`
- `page_size`

Response: HTTP `200`, paginated reimbursement objects:

```json
{
  "id": 3,
  "employee": {"id": 7, "email": "employee@example.com", "name": "Employee"},
  "expense": {"id": 12, "expense_id": "EXP012"},
  "amount": "1250.00",
  "status": "pending",
  "requested_on": "2026-09-06T10:00:00+05:30",
  "resolved_on": null,
  "advance_adjusted_amount": "0.00"
}
```

### Adjust advance

```http
POST /api/reimbursements/<reimbursement_id>/adjust-advance/
```

Requires `expenses.process_reimbursement`. No request body is required.

For a reimbursement linked to an `is_advance=true` approved expense, the adjustment is:

```text
min(reimbursement.amount, linked_advance_expense.amount)
```

The result is stored in `advance_adjusted_amount` and an `Advance Adjusted` ActivityLog entry is created.

### Approve reimbursement

```http
POST /api/reimbursements/<reimbursement_id>/approve/
```

Approval is blocked if the linked advance amount has not been adjusted. On success, status becomes `approved` and `resolved_on` is set.

### Reject reimbursement

```http
POST /api/reimbursements/<reimbursement_id>/reject/
```

On success, status becomes `rejected`, `resolved_on` is set, and a reimbursement ActivityLog entry is created.

## 6. History and deleted expenses

### Activity history

```http
GET /api/expenses/history/
```

Optional query parameters:

- `action=<action_name>`
- `page`
- `page_size`

History is read directly from `ActivityLog`; it is not reconstructed from the current Expense row.

Response: HTTP `200`, paginated records:

```json
{
  "id": 31,
  "expense_id": "EXP012",
  "action": "Approved",
  "actor": {"id": 21, "email": "finance@example.com", "name": "Finance"},
  "action_date": "2026-09-06T12:00:00+05:30",
  "snapshot": {
    "expense_id": "EXP012",
    "status": "approved",
    "payment_status": "unpaid",
    "amount": "1250.00"
  }
}
```

### Deleted expenses

```http
GET /api/expenses/deleted/
```

Optional query parameters:

- `page`
- `page_size`

Returns Expense rows where `is_deleted=true`, subject to the same `can_view` scope. These rows do not appear in `GET /api/expenses/`.

## 7. Reports

### Summary report

```http
GET /api/reports/summary/?start=2026-09-01&end=2026-09-30
```

Query parameters:

- `start=YYYY-MM-DD` — optional
- `end=YYYY-MM-DD` — optional

If both are supplied, `end` must be on or after `start`.

The report uses the same organization and `can_view` scope as the expense list and excludes soft-deleted expenses.

Response: HTTP `200`

```json
{
  "filters": {"start": "2026-09-01", "end": "2026-09-30"},
  "totals": {
    "total_expenses": "30000.00",
    "paid": "12000.00",
    "pending": "18000.00",
    "reimbursements": "5000.00"
  },
  "counts": {
    "expenses": 12,
    "paid": 5,
    "pending": 7,
    "reimbursements": 3
  },
  "category_breakdown": [
    {"category_id": 1, "category": "Travel", "amount": "15000.00", "count": 6}
  ],
  "expenses_over_time": [
    {"date": "2026-09-06", "amount": "1250.00", "count": 1}
  ]
}
```

Definitions:

- `total_expenses`: amount of all visible, non-deleted expenses in the date range
- `paid`: amount of visible expenses with `payment_status=paid`
- `pending`: amount of visible approved expenses with `payment_status=unpaid`
- `reimbursements`: amount of visible reimbursement requests linked to the scoped expenses
- `category_breakdown`: amount and count grouped by category
- `expenses_over_time`: amount and count grouped by expense date

### Export report

```http
GET /api/reports/export/?format=xlsx&start=2026-09-01&end=2026-09-30
GET /api/reports/export/?format=pdf&start=2026-09-01&end=2026-09-30
```

Query parameters:

- `format=xlsx|pdf` — defaults to `xlsx`
- `start=YYYY-MM-DD` — optional
- `end=YYYY-MM-DD` — optional

The export uses exactly the same scope and report calculations as the summary endpoint.

XLSX response:

- HTTP `200`
- Content type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- Download name: `expense-report.xlsx`
- Sheets:
  - `Expense Summary`
  - `Category Breakdown`
  - `Expenses Over Time`

PDF response:

- HTTP `200`
- Content type: `application/pdf`
- Download name: `expense-report.pdf`

Invalid format response: HTTP `400`

```json
{"format": "Use xlsx or pdf."}
```

## Common errors

```json
{"detail": "Authentication credentials were not provided."}
```

HTTP `401` means authentication is missing or invalid.

```json
{"detail": "You do not have permission to perform this action."}
```

HTTP `403` means the authenticated user lacks the required organization membership or RBAC permission.

Validation failures return HTTP `400`, for example:

```json
{"receipt": ["A receipt is mandatory before submission."]}
```

There are no hard-delete endpoints for expenses or categories. Expense cancellation is a soft-delete operation, and category removal is represented by `is_active=false`.
