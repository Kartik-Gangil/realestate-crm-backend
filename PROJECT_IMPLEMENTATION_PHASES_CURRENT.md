# Real Estate CRM — Current-State Implementation Phases

## Purpose

This is the executable plan for the repository as it exists now. The earlier
`PROJECT_IMPLEMENTATION_PHASES.md` is retained as the requirements baseline,
but it describes the project as greenfield and should not be used as the sprint
order.

## Current assessment

### Already present in the backend

- Django/DRF project structure, migrations, token authentication, organization
  tenancy, membership access scopes, roles, permissions, and audit foundations.
- Leads, follow-up calls, site visits, plot inventory, holds, bookings,
  installments, payments, refunds/adjustments, receipts, agreements, registry,
  possession, and plot-selection services/models.
- Customer and employee document repositories, document verification history,
  employee profiles, departments, attendance, leave, employee documents, and
  system settings.
- Expenses and reimbursement workflow, including reporting/export endpoints.

### Present but not release-ready

- The frontend has screens and API clients for most implemented domains, but the
  production build currently fails on TypeScript errors and duplicate API
  declarations.
- Telecalling, Communications, and Loans still read mock data or have no
  corresponding complete backend workflow.
- Several frontend screens are placeholders or only partially connected to the
  backend; a visible route is not evidence that its use case is complete.
- The full backend suite runs 75 tests but currently has 5 errors caused by
  media-file writes being denied during tests. This must be fixed before using
  the suite as a release signal.

### Important architectural gaps to resolve explicitly

- Define the canonical Customer model and customer identity lifecycle. Current
  customer-facing flows are coupled to lead/booking/document relationships and
  must be checked for consistent ownership and organization isolation.
- Define whether Loans is in the first release. It has a frontend route and
  mock data, but no complete backend domain in the current app inventory.
- Define the provider contracts and credentials for Meta/Google lead sync,
  WhatsApp, SMS, email automation, eKYC, and telephony before implementing
  integrations.

## Revised phase sequence

| Phase | Goal | Main output | Exit gate |
| --- | --- | --- | --- |
| 0 | Stabilize the baseline | Clean test media isolation, passing backend checks, passing frontend build, documented environment and migration procedure | Backend tests pass; `pnpm run build` passes; no pending migrations |
| 1 | Establish the platform contract | Versioned API conventions, auth/session behavior, organization context, canonical RBAC checks, error/loading conventions, and frontend route guards | One authenticated user can switch organization and receive the same permission result in UI and API |
| 2 | Deliver the lead-to-visit slice | Lead create/list/detail/edit, assignment, follow-ups, telecalling queue/dispositions, site-visit schedule/reschedule/outcome | A lead can move from acquisition through a completed site visit without mock data |
| 3 | Deliver inventory-to-booking | Project/block/plot inventory, map/list views, hold countdown/expiry, conflict recheck, booking, pricing, receipt/agreement | Two users cannot book the same plot; an end-to-end booking is persisted and auditable |
| 4 | Deliver customer 360 and compliance | Canonical customer profile, linked lead/visit/booking/payment timeline, customer documents, verification, expiry rules | Customer data and documents are organization-isolated and linked consistently to bookings |
| 5 | Complete money and registry operations | Payment collection/allocation, dues/ledger, installments, refunds/adjustments, registry charges/status/documents, possession handoff | Financial totals reconcile from transaction records; registry can progress from pending to completed |
| 6 | Complete internal operations | Employee lifecycle, roles/permissions UI, attendance, leave, employee documents, expenses, approvals, reimbursements | Manager/admin workflows work end-to-end with permission and audit coverage |
| 7 | Replace mocks with business automation | Communication templates/logs, trigger rules, notifications, provider adapters, telephony integration, and a decision on Loans | Every enabled screen uses a real API or is explicitly marked out of scope |
| 8 | Release hardening | Security review, isolation tests, integration tests, performance checks, backup/restore procedure, observability, deployment runbook, UAT | UAT sign-off, rollback plan, reproducible deployment, and no critical defects |

## How to execute each phase

Each phase is a vertical slice, not a frontend-only or backend-only milestone.
For every use case, complete these in order:

1. Confirm the business rule and ownership boundary.
2. Confirm or add the database model and migration.
3. Implement service logic with organization isolation and permission checks.
4. Add API serializers, validation, error responses, and focused tests.
5. Connect the frontend API client and screen states (loading, empty, error,
   success, forbidden, and concurrency where relevant).
6. Run the phase exit gate and update the API documentation.

## Immediate work order

1. Fix test media storage so tests use a temporary media root and clean up after
   each run; do not loosen production file permissions to make tests pass.
2. Fix the frontend TypeScript build errors, starting with duplicate inventory
   API declarations and unused/dead state, then the remaining type mismatches.
3. Create a route-to-API matrix for every page and mark each page as
   `real-api`, `partial`, `mock`, or `out-of-scope`.
4. Resolve the Customer model/identity decision and Loans scope before Phase 4
   and Phase 7 implementation begins.
5. Start Phase 1 only after the baseline gate is green; then execute Phase 2 as
   the first user-visible production slice.

## Release status definitions

- **Implemented:** code exists and has focused automated coverage.
- **Integrated:** frontend and backend use the same real workflow and error
  contract.
- **Accepted:** the workflow passes its phase exit gate and user acceptance.
- **Mock/placeholder:** UI or data exists only to demonstrate layout and cannot
  be counted toward release functionality.

