# Expense Module — Frontend Implementation Instructions

## Objective

Implement the Expense module frontend against the completed backend APIs documented in:

- `expense-url-doc.md` — complete API URL, query, request and response reference
- `expense-doc.md` — backend domain, workflow, RBAC and business-rule reference

The frontend must support expense categories, expense CRUD, approval workflow, payments, reimbursements, history, deleted expenses and reports.

## Mandatory UI rule

**If the UI for an API already exists, integrate that API into the existing UI. If it does not exist, create the UI first and then integrate the API. Always follow the same design conventions, style and patterns used throughout the full codebase. Do not create a new color palette or invent an independent visual system.**

Before creating any component:

1. Search the frontend for an existing page, table, form, modal, drawer, filter bar, upload control, status badge, approval stepper, chart, export button or pagination component that can be reused.
2. Reuse the existing API client, authentication handling, route guards, query hooks, form validation, toast/notification system and shared components.
3. Reuse existing spacing, typography, border radius, shadows, table patterns, responsive breakpoints and status colors.
4. Use the existing color tokens/theme variables only. Do not add a new palette.
5. Match the existing page layout, navigation/sidebar behavior and mobile/responsive conventions.

## API base and authentication

Use the existing authenticated API client. Do not manually duplicate token handling inside Expense components.

Primary endpoints use `/api/`. The backend also exposes `/api/v1/` aliases; follow the frontend codebase's existing version convention.

Send the authenticated token using the existing project convention, normally:

```http
Authorization: Token <token>
```

## RBAC and visibility

The UI must reflect backend permissions but must never treat UI hiding as security. The backend remains authoritative.

Expense permission codes:

- `expenses.view_own`
- `expenses.edit_own`
- `expenses.submit`
- `expenses.view_team`
- `expenses.approve`
- `expenses.manage_categories`
- `expenses.process_payment`
- `expenses.process_reimbursement`
- `expenses.reports`

Use the existing user-permission/tab-permission mechanism to show or hide navigation and actions. Handle `401`, `403` and `400` responses from the backend even when an action was hidden.

Suggested UI behavior:

- Employees see their permitted expenses and own history.
- Managers see the approval queue when they have approval permission.
- Finance/admin/custom roles see category management, payment, reimbursement and report controls according to their assigned permissions.
- Never hardcode a role name such as `finance` when a permission check is available.

## Required frontend screens and API integration

### 1. Expense list

Route should follow the existing application navigation convention.

Integrate:

```http
GET /api/expenses/
```

Support:

- status filter
- payment status filter
- category filter
- date-from/date-to filter
- description/expense-ID search
- pagination
- loading, empty and error states
- refresh after create, edit, submit or cancel

Show at minimum:

- Expense ID
- Date
- Category
- Description
- Amount
- Paid by / submitted by
- Approval status
- Payment status
- Advance indicator
- Receipt availability
- Actions allowed by permission and current status

Do not show cancelled/deleted expenses in the main list; use the Deleted/History views for them.

### 2. Add expense

Integrate:

```http
POST /api/expenses/
```

Create a form using existing form controls and validation patterns.

Fields:

- organization, when the user belongs to multiple organizations
- date
- category
- amount
- description
- payment method: Cash, Card, Bank Transfer, UPI
- paid by
- receipt
- notes
- project reference
- Mark as Advance checkbox

Provide two actions:

- Save as Draft — send `action=draft`
- Submit for Approval — send `action=submit` or `action=submit-for-approval`

Receipt behavior:

- Draft can be saved without a receipt.
- Submit must require a receipt in the UI, but still handle the backend validation error.
- Allow JPG, JPEG, PNG and PDF only.
- Enforce/display the 5 MB maximum before upload.
- Use the existing file-upload component and error display pattern.

Use `multipart/form-data` when a receipt is uploaded.

### 3. Edit expense

Integrate:

```http
GET /api/expenses/<id>/
PATCH /api/expenses/<id>/
```

Allow editing only for the submitter's `draft` or `changes_requested` expenses with `expenses.edit_own`.

Approved expenses must render read-only. If the backend returns HTTP `400` for an approved edit, show the existing error/toast pattern and refresh the detail state.

### 4. Expense detail and approval workflow

The detail screen should display:

- expense information
- receipt preview/download link using the existing file/document viewer pattern
- approval steps as a vertical stepper if that component already exists
- activity timeline using the existing timeline/history component if available
- payment status/details when present

Integrate:

```http
GET /api/expenses/<id>/
POST /api/expenses/<id>/cancel/
```

Cancellation is soft-delete. Label the action clearly and use the existing confirmation modal. Do not add a hard-delete button.

### 5. Manager approval queue

Integrate:

```http
GET /api/expenses/pending-approval/
POST /api/expenses/<id>/approve/
POST /api/expenses/<id>/reject/
POST /api/expenses/<id>/request-changes/
```

Queue requirements:

- paginated table/list
- show submitter, amount, category, date, receipt and current step
- approve action with confirmation if that is the existing convention
- reject action requires a comment
- request-changes action accepts a comment
- refresh the queue after every successful action
- show backend validation and permission errors

After approval, show the Finance step as pending. After request-changes, show the expense as editable by the submitter.

### 6. Payment screens

Integrate:

```http
GET /api/payments/unpaid/
GET /api/payments/paid/
POST /api/expenses/<id>/mark-paid/
```

Use existing tabs, segmented controls or table conventions for unpaid/paid views.

Mark-paid form fields:

- payment method
- payment date
- reference number
- paid amount
- paid by

Only show the payment action when the user has `expenses.process_payment` and the expense is approved/unpaid. Still handle backend `400`/`403` responses.

### 7. Reimbursement screens

Integrate:

```http
GET /api/reimbursements/
POST /api/reimbursements/<id>/adjust-advance/
POST /api/reimbursements/<id>/approve/
POST /api/reimbursements/<id>/reject/
```

Support status filtering: `pending`, `approved`, `rejected`.

For linked advance expenses:

- display the advance amount
- display the adjusted amount
- provide the Adjust Advance action before approval
- explain backend approval blocking when adjustment is incomplete

Reject/approve actions must refresh the reimbursement row/list.

### 8. History and deleted expenses

Integrate:

```http
GET /api/expenses/history/
GET /api/expenses/deleted/
```

History must render ActivityLog records directly as returned by the backend. Do not rebuild historical rows from the current expense detail.

History filters:

- action
- pagination

Deleted expenses should be read-only. Do not show restore or hard-delete actions unless a future backend contract explicitly adds them.

### 9. Categories management

Integrate:

```http
GET /api/categories/
POST /api/categories/
PATCH /api/categories/<id>/
```

Use the existing settings/admin table and modal/form patterns.

Support:

- list active/inactive categories
- organization filter where applicable
- create category
- edit category
- toggle `is_active`

There is no delete endpoint. The UI must use Active/Inactive status instead of a destructive delete action.

Only users with `expenses.manage_categories` should see category management controls.

### 10. Reports and exports

Integrate:

```http
GET /api/reports/summary/?start=YYYY-MM-DD&end=YYYY-MM-DD
GET /api/reports/export/?format=xlsx|pdf&start=YYYY-MM-DD&end=YYYY-MM-DD
```

Report screen should reuse existing dashboard/report components, cards, chart libraries and date-range controls.

Display:

- Total Expenses
- Paid
- Pending
- Reimbursements
- Category breakdown
- Expenses Over Time time series

The summary response contains:

```json
{
  "filters": {"start": "2026-09-01", "end": "2026-09-30"},
  "totals": {
    "total_expenses": "30000.00",
    "paid": "12000.00",
    "pending": "18000.00",
    "reimbursements": "5000.00"
  },
  "counts": {"expenses": 12, "paid": 5, "pending": 7, "reimbursements": 3},
  "category_breakdown": [],
  "expenses_over_time": []
}
```

Export behavior:

- Use the existing download helper in the frontend.
- Do not parse XLSX/PDF as JSON.
- Respect the response filename/content type.
- Show a loading state while generating the export.
- Show the existing error notification if export fails.
- Do not create a client-side report calculation that differs from the backend summary.

The report API is scoped with the same visibility rules as the expense list.

## General UX and engineering requirements

Use the existing project conventions for:

- API service modules/hooks
- query caching and invalidation
- route registration
- protected routes
- form state and validation
- toast/error messages
- confirmation dialogs
- tables and pagination
- responsive layouts
- loading skeletons/spinners
- empty states
- file previews/downloads
- date and currency formatting

Keep server values authoritative. Do not duplicate workflow transitions in frontend state without refetching or invalidating the relevant query.

After every successful mutation, refresh or invalidate the affected queries:

- expense list
- expense detail
- approval queue
- payment queue
- reimbursement list
- history/deleted list
- report summary where relevant

## Validation and error handling

Handle at least:

- `401` — redirect/use the existing authentication-expired flow
- `403` — show the existing permission-denied behavior
- `400` — display field-level or form-level backend validation
- `404` — show the existing not-found state
- `429` — use the existing throttling/retry message
- `5xx` — use the existing generic server-error state

Never silently ignore a failed mutation.

## Completion checklist

- Existing UI was reused wherever available.
- New UI was created only for missing use cases.
- Existing design system, color tokens and layout patterns were followed.
- No new color palette was created.
- No hard-delete action was added for expenses or categories.
- All API calls use the shared authenticated API client.
- All pages support loading, empty, error and permission states.
- Receipt upload validation matches the backend.
- Approval, payment and reimbursement actions use backend permissions and statuses.
- XLSX/PDF downloads work with the backend response headers.
- Frontend tests cover list, create draft, submit, edit, approve, reject, payment, reimbursement, category, history and report flows.
