# Expense Module Documentation

## Overview

The Expense module was implemented in phases today. It is organization-scoped and uses the existing organization RBAC system. The module currently supports:

- Expense categories
- Expense creation and editing
- Draft and submit-for-approval workflows
- Manager approval workflow
- Payment processing
- Reimbursement adjustment and approval
- Activity history
- Soft deletion and deleted-expense listing

Expense APIs are mounted under `/api/`. Versioned aliases are also available under `/api/v1/`.

## Implemented application structure

Main files:

- `expenses/models.py` — domain models and validation
- `expenses/services.py` — permissions and transactional business rules
- `expenses/serializers.py` — API response representations
- `expenses/views.py` — API views
- `expenses/urls.py` — API routes
- `expenses/admin.py` — internal Django admin registration
- `expenses/management/commands/seed_expense_categories.py` — default category seeding
- `expenses/tests.py` — foundation tests
- `expenses/tests_api.py` — API and workflow tests

The app is registered in `config/settings.py` and routes are included in `config/urls.py`.

## Models

### ExpenseCategory

Organization-scoped category model:

- `organization`
- `name`
- `description`
- `is_active`
- `created_at`
- `updated_at`

Category names are unique within an organization. Categories are deactivated through `is_active`; they are not hard-deleted through the admin or API.

### Expense

Fields:

- `organization`
- `date`
- `category`
- `amount`
- `description`
- `payment_method`: `cash`, `card`, `bank_transfer`, `upi`
- `paid_by`
- `submitted_by`
- `receipt`
- `notes`
- `project_reference` — currently a plain text field
- `is_advance`
- `status`
- `payment_status`
- `is_deleted`
- `created_at`
- `updated_at`

The human-readable expense ID is exposed as a property over the database primary key:

```text
EXP001
EXP002
EXP003
```

Expense statuses:

- `draft`
- `pending_approval`
- `changes_requested`
- `approved`
- `rejected`
- `cancelled`

Payment statuses:

- `unpaid`
- `paid`

Receipt validation:

- Optional while saving a draft
- Mandatory when submitting for approval
- Allowed extensions: JPG, JPEG, PNG, PDF
- Maximum size: 5 MB

### ApprovalStep

Stores the vertical approval workflow:

- `expense`
- `step_name`
- `actor`
- `status`: `pending`, `done`, `rejected`
- `acted_at`
- `comment`

Created workflow steps include:

- `Submitted`
- `Manager Review`
- `Finance`

### Payment

One-to-one payment record for an expense:

- `expense`
- `payment_method`
- `payment_status`
- `payment_date`
- `reference_no`
- `paid_by`
- `paid_amount`

Only approved, unpaid expenses can be marked paid.

### ReimbursementRequest

Fields:

- `employee`
- `expense` — nullable, allowing future aggregated reimbursement support
- `amount`
- `status`: `pending`, `approved`, `rejected`
- `requested_on`
- `resolved_on`
- `advance_adjusted_amount`

The current implementation treats the linked `expense` as the authoritative advance link when it is marked `is_advance=True`.

### ActivityLog

Append-only audit record:

- `expense` — nullable
- `action`
- `actor`
- `action_date`
- `snapshot`

The snapshot stores key expense values at the time of the action so history is not re-derived from the current expense state.

## RBAC permissions

Expense permissions were added to the existing `organizations.Permission` catalogue:

- `expenses.view_own`
- `expenses.edit_own`
- `expenses.submit`
- `expenses.view_team`
- `expenses.approve`
- `expenses.manage_categories`
- `expenses.process_payment`
- `expenses.process_reimbursement`
- `expenses.reports`

The existing role system remains dynamic. Roles receive permissions through `OrganizationRole.permissions`; the Expense module does not depend on a hard-coded Finance role.

Default compatibility behavior:

- Organization admins receive all Expense permissions
- Managers receive own-expense permissions, team visibility and approval permissions
- Employee-compatible memberships receive own-expense permissions
- Custom Finance roles can be created by assigning the relevant payment/reimbursement permissions

## Phase 1 — Foundation

Implemented:

- Models and migrations
- Model validation
- Permission/service helpers:
  - `can_view(user, expense)`
  - `can_edit(user, expense)`
  - `can_approve(user, expense)`
  - `can_process_payment(user, expense)`
  - `can_process_reimbursement(user, reimbursement)`
- Transactional services for submit, cancel, approval, payment and reimbursement actions
- Django admin registration for all Expense models
- Default category seed command

Seed command:

```powershell
python manage.py seed_expense_categories
```

For one organization only:

```powershell
python manage.py seed_expense_categories --organization acme
```

Default categories:

- Travel
- Marketing
- Office Supplies
- Utilities
- Others

## Phase 2 — Expense CRUD APIs

### List and create

```http
GET /api/expenses/
POST /api/expenses/
```

List filters:

- `status`
- `payment_status`
- `category`
- `date_from`
- `date_to`
- `search` — description or expense ID
- `page`
- `page_size`

The list excludes soft-deleted expenses and applies `can_view` to every result.

Create behavior:

- `action=draft` saves a draft
- `action=submit` submits for approval
- `action=submit-for-approval` also submits for approval
- Organization can be supplied by slug or ID in `organization`
- If a user belongs to only one organization, `organization` may be omitted
- `submitted_by` defaults to the authenticated user
- `paid_by` defaults to the authenticated user

Submitting requires a valid receipt. On successful submission:

1. Expense status becomes `pending_approval`
2. `Submitted` step is created as `done`
3. `Manager Review` step is created as `pending`
4. A `Submitted` ActivityLog entry is created

### Detail and edit

```http
GET /api/expenses/<id>/
PATCH /api/expenses/<id>/
```

Only the submitting employee can edit their own `draft` or `changes_requested` expense, subject to `expenses.edit_own`.

Approved expenses are read-only and return HTTP 400 on edit attempts.

### Cancel

```http
POST /api/expenses/<id>/cancel/
```

Cancellation:

- Sets `status=cancelled`
- Sets `is_deleted=True`
- Writes a `Cancelled` ActivityLog entry
- Removes the expense from the main list
- Keeps the expense available in the deleted/history views

Approved-expense cancellation is currently blocked until the final cancellation policy is confirmed.

## Phase 3 — Manager Approval Workflow

### Pending approval queue

```http
GET /api/expenses/pending-approval/
```

The queue includes only expenses that:

- Are `pending_approval`
- Are not soft-deleted
- Have a pending `Manager Review` step
- Are actionable by the current user

Assigned manager resolution uses the submitter's `OrganizationMembership.reporting_manager` relation. If no reporting manager is configured, a manager-role fallback is used.

### Approve

```http
POST /api/expenses/<id>/approve/
```

On approval:

- Current `Manager Review` step becomes `done`
- Actor and action time are saved
- Expense status becomes `approved`
- A pending `Finance` step is created
- `Approved` ActivityLog entry is created

### Reject

```http
POST /api/expenses/<id>/reject/
```

The request requires a non-empty `comment`.

On rejection:

- Current approval step becomes `rejected`
- Expense status becomes `rejected`
- Actor, action time and comment are saved
- `Rejected` ActivityLog entry is created

### Request changes

```http
POST /api/expenses/<id>/request-changes/
```

On request-changes:

- Current approval step becomes `rejected` with the manager comment
- Expense status becomes `changes_requested`
- Submitter can edit the expense again
- `Changes Requested` ActivityLog entry is created

When the submitter resubmits, the existing Manager Review step is reset to `pending`.

Only the assigned manager, Finance/custom approval role, admin, or platform admin can perform approval actions.

## Phase 4 — Payment and Reimbursement

### Payment queues

```http
GET /api/payments/unpaid/
GET /api/payments/paid/
```

Both queues contain only expenses where:

- `status=approved`
- `is_deleted=False`
- `payment_status` matches the queue
- The current user passes `can_view`

### Mark paid

```http
POST /api/expenses/<id>/mark-paid/
```

Request fields:

```json
{
  "payment_method": "upi",
  "payment_date": "2026-09-06",
  "reference_no": "UPI-123",
  "paid_amount": "5000.00",
  "paid_by": 12
}
```

The service validates the expense is approved and unpaid, creates a Payment row, sets the Expense payment status to `paid`, and writes a `Paid` ActivityLog entry.

Only users with `expenses.process_payment` can mark payments paid.

### Reimbursement list

```http
GET /api/reimbursements/
```

Supported filter:

- `status`
- `page`
- `page_size`

Employees can see their own reimbursement requests. Finance/admin/custom reimbursement roles can see requests they are authorized to process.

### Adjust advance

```http
POST /api/reimbursements/<id>/adjust-advance/
```

For a reimbursement linked to an `is_advance=True` expense, the adjustment is calculated as the smaller of:

- reimbursement amount
- linked advance expense amount

The result is stored in `advance_adjusted_amount` and an `Advance Adjusted` ActivityLog entry is written.

### Approve/reject reimbursement

```http
POST /api/reimbursements/<id>/approve/
POST /api/reimbursements/<id>/reject/
```

Reimbursement approval is blocked while the required advance amount has not been adjusted. Approval/rejection also records `resolved_on` and creates an ActivityLog entry.

Only users with `expenses.process_reimbursement` can adjust, approve or reject reimbursement requests.

## Phase 5 — History and deleted expenses

### Activity history

```http
GET /api/expenses/history/
```

This endpoint reads ActivityLog rows directly. It does not reconstruct history from the current Expense row.

Response records include:

- Activity log ID
- Expense ID from the linked expense or snapshot
- Action
- Actor
- Action date
- Historical snapshot

Optional filter:

- `action`
- `page`
- `page_size`

Deleted expenses remain represented in ActivityLog because their foreign key uses `SET_NULL` only if the expense is physically purged. The application does not expose a purge endpoint.

### Deleted expenses

```http
GET /api/expenses/deleted/
```

Returns Expense rows where `is_deleted=True`, scoped through the same `can_view` logic. These rows are excluded from `/api/expenses/`.

## Soft-delete audit

The only Expense deletion behavior exposed by the module is soft cancellation:

```text
Expense.status = cancelled
Expense.is_deleted = True
ActivityLog(action = Cancelled)
```

There is no `DELETE /api/expenses/<id>/` endpoint. Django admin hard-delete is also disabled for Expense. ActivityLog, ApprovalStep and related audit records are read-only in admin.

## Migrations

Expense-related migrations created/applied:

- `organizations.0010_expense_permissions`
- `organizations.0011_expense_manager_permissions`
- `expenses.0001_initial`
- `expenses.0002_align_initial_model_state`
- `expenses.0003_payment_method`

## Verification

The final verification after the History phase completed successfully:

```text
System check: OK
Migration check: No changes detected
Full test suite: 73 passed
Failures: 0
```

Expense-focused tests cover model validation, receipt rules, draft/submit behavior, approval workflow, payment queues, mark-paid, advance adjustment, reimbursement approval blocking, soft deletion, history and deleted-expense visibility.

## Current intentional limitations

- Expense APIs currently support reimbursement listing and processing, but no reimbursement-create endpoint was added in the requested phases.
- `project_reference` is currently plain text because the current inventory implementation does not have a Project model.
- Approved-expense cancellation is blocked until the client confirms the final cancellation policy.
- Reimbursement advance linking currently uses the single nullable `ReimbursementRequest.expense` relation; aggregate multi-expense linking can be added in a future phase.
