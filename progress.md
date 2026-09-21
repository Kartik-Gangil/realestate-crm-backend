# Backend Progress

**Version:** v1.47  
**Last updated:** 2026-09-20  
**Status:** Broad functional foundation implemented; specification compliance is incomplete across 18 phases (0–17).

## v2.0 specification alignment

This update compares the repository with the current `CRM_REQUIREMENTS_SPEC.md`.
The specification now defines Phase 6 calls as external phone calls recorded
through one manual call-log submission. The backend has been reworked to remove
the superseded in-app start/end call-session workflow and implement the confirmed
FR-P6-08/API-P6-06 contract. The specification also includes Phase 17 for Reporting,
Analytics, and Role-Based Dashboards, resolves eKYC timing as a
pre-booking-confirmation requirement, confirms Registry and Expenses are in
scope, and confirms that payments are manually entered without a payment
gateway. Its phase order and hard gates are not yet fully satisfied by the
current code.

| Specification area | Current status |
| --- | --- |
| Phase 0: project foundation | **Backend complete; frontend exit gate pending** — canonical organization/project fields, assigned discovery, Admin/Super Admin project CRUD, health/readiness, centralized `X-Project-ID` validation, and automatic row-level project binding/filtering cover business domains, operational HR records, project-consumed settings, and audits. Organization identity, memberships, canonical roles, and platform access remain organization-wide by design. Same-organization cross-project leakage and project-local uniqueness tests pass. Shell switching/unsaved-change requirements remain frontend work. |
| Phase 1: authentication and session security | **Partial** — password hashing, lockout, reset, logout invalidation, route restrictions, and OTP foundations exist; remaining OTP login/rate-limit and configurable inactivity-timeout acceptance work is still pending. |
| Phase 2: project context and master data | **Backend complete; frontend exit gate pending** — FR-P2-01 through FR-P2-04, NFR-P2-01/NFR-P2-02, DM-P2-01 through DM-P2-03, and API-P2-01 through API-P2-05 are implemented and tested: category→item master data, cache-aside parameters, protected system items, strict Admin/Super Admin mutation authorization, typed coercion, active-only consumer lookups, canonical PUT updates, and project-scoped lead-source/site-visit-outcome/plot-status/lead-status catalogues. |
| Phase 3: RBAC and user administration | **Backend core implemented; frontend and full cross-module exit gate pending** — FR-P3-01 project-scoped user administration, FR-P3-02 custom role permission matrix, FR-P3-03 dynamic permission checks on role/user management paths, FR-P3-04 before/after/IP audit records for role/user mutations, FR-P3-05 deactivated-account blocking, FR-P3-06 system-role protection, and FR-P3-07 project assignment foundations are implemented and covered by Phase 3 tests. Remaining work is applying the permission interceptor/audit coverage uniformly to every legacy protected endpoint and completing UI requirements. |
| Phase 4: lead acquisition and imports | **Backend core implemented; frontend exit gate pending** — FR-P4-01 provider sync endpoints for Meta/Google with external-lead idempotency, FR-P4-02 manual leads with phone validation, FR-P4-03 5MB asynchronous CSV batches in 500-row chunks with persisted progress/error reports, FR-P4-04 configurable weighted duplicate scoring, FR-P4-05 duplicate warning/merge/create-anyway APIs, and FR-P4-06 role restrictions are implemented and tested. Provider credential adapters and frontend wizard/modal requirements remain. |
| Phase 5: lead lifecycle and assignment | **Backend core implemented; frontend exit gate pending** — FR-P5-01 dynamic filters/pagination/sorting, FR-P5-02 guarded status state machine, FR-P5-03 assignment reason/history, FR-P5-04 transactional bulk actions, FR-P5-05 converted-lead immutability, FR-P5-06 immutable status history, FR-P5-07 owner/team-view authorization, and FR-P5-08 manager/admin reassignment controls are implemented and tested. Frontend lifecycle/filter/bulk components and final cross-module exit verification remain. |
| Phase 6: telecalling | **Backend implemented for v2.0** — FR-P6-01 queue ordering uses pending-attempt status and earliest follow-up time only, with deterministic ties, role/tenant scoping, tabs, pagination, and tests. API-P6-06 now exposes the organization-scoped manual call-log submission with required active master-data disposition and notes, defaulted/editable call timestamp, optional MP3/WAV/M4A/AAC recording up to 25 MB, conditional follow-up creation, reminder outbox handoff, assignment authorization, and audit logging. Dispositions now advance the Phase 5 lead lifecycle through valid transitions (`interested` reaches Interested via Contacted; retry/unreachable dispositions reach Contacted; terminal negative dispositions reach Lost) without regressions. Obsolete API-P6-02/API-P6-03 routes, timer state, duration metrics, and active-session fields are removed. API-P6-04 now schedules follow-ups only and cannot record completed call activity. FR-P6-07 team analytics and queue redistribution remain implemented. Actual Phase 14 reminder dispatch/providers remain Phase 14 work. |
| Phase 7: site visits | **Backend core implemented; frontend exit gate pending** — FR-P7-01 executive conflict detection, FR-P7-02 guarded visit state machine, FR-P7-03 completion score boost, FR-P7-04 validated outcomes/ratings, FR-P7-05 active-lead gate, FR-P7-06 project-aware configurable future-day limit, and FR-P7-07 executive ownership/manager visibility are implemented and tested. Frontend calendar/map handoff and final cross-module exit verification remain. |
| Phase 8: inventory | **Backend core implemented; frontend exit gate pending** — FR-P8-01/02 inventory CRUD and lifecycle, FR-P8-03 atomic row locking for block/hold, FR-P8-04 expired-hold release worker service, FR-P8-05 unavailable-plot protection, FR-P8-06 transactional bulk status history, and FR-P8-07 RBAC including Site Visit Executive temporary holds are implemented and tested. Frontend layout/countdown/exit-gate verification remains. |
| Phase 9: booking | **Backend complete; frontend exit gate pending** — atomic booking/plot-hold/payment transaction with rollback, idempotency-key replay protection, configurable minimum payment and 7-day default expiry, pending-booking expiry worker, qualified + verified-eKYC confirmation gate, and sequential booking-receipt PDF endpoint are implemented and tested. The multi-step frontend wizard/conflict screen remains outside this backend repository. |
| Phase 10: customer 360 | **Backend core implemented; frontend exit gate pending** — canonical Customer and CustomerNote records, lead-conversion auto-creation, organization-scoped phone/email/government-ID uniqueness, non-destructive status lifecycle, duplicate-profile response, assigned-user access, notes, and chronological 360 aggregation across lead-linked visits/bookings/payments/documents are implemented and tested. Existing modules retain their Lead foreign keys for backward compatibility; UI dashboard/list/slide-over remains pending. |
| Phase 11: payments | **Backend core implemented; PDF/UI exit gate pending** — manual multi-due collection, payment idempotency via required `X-Idempotency-Key`, immutable payment/allocation rows with adjustment/refund correction paths, exact Decimal advance-balance handling, cheque Pending Realization, overdue-installment refresh, Admin-only refund approval, receipt records, and Phase 9/10 cross-phase regression coverage are implemented and tested. Printable payment-receipt PDF, payment UI, and final ledger exit-gate verification remain. No payment gateway integration is required by v2.0. |
| Phase 12: documents/eKYC | **Backend core implemented; real provider/cloud delivery pending** — FR-P12-01 secure PDF/JPG/PNG upload limits, AES-256-GCM document storage, provider-neutral mock eKYC verification with encrypted ID, outage retry queue, manager/admin gate, booking-compatible verified status, and 30-day expiry notification outbox are implemented and tested. Real Aadhaar/PAN/address/face provider adapters, cloud object storage/pre-signed URL delivery, actual email/SMS dispatch, and frontend pending banners remain. |
| Phase 13: registry | **Backend core implemented; frontend/refund handoff pending** — lifecycle, fixed/percentage charges, confirmed-booking + zero-dues + verified-eKYC initiation gate, verified legal-document completion checklist, immutable status history, Admin/Legal permission path, and cancellation → `Booked` behavior are implemented and tested. Refund handling prompt/actual payment-refund workflow and frontend checklist remain. |
| Phase 14: communications | **Not complete** — provider adapters, templates, triggers, opt-out handling, operational hours, and dispatch logs are not complete. |
| Phase 15: employee/HRMS | **Backend core implemented; UI and Phase 14 notification delivery pending** — employee directory/profile APIs, attendance check-in/out with calculated hours, Casual/Sick/Paid/Earned leave, reporting-manager approval, overlap rejection, balance deduction, quarterly performance reviews, and deactivated-account login blocking are implemented and tested. Frontend screens and actual approval notifications remain outside this backend scope. |
| Phase 16: expenses | **Backend core implemented; frontend/reporting polish pending** — expense logging, configurable ₹5,000 receipt threshold, approval/rejection/reimbursement workflow, mandatory rejection reason, Admin-only cancellation, model-level approved-record immutability, role scoping, and isolated media tests are implemented and tested. |
| Phase 17: reporting and role dashboards | **Not started** — no complete reporting library, custom report builder, role-scoped report APIs, or specification-defined role dashboards are implemented. |

## Global specification hard gates still outstanding

- Explicit state-machine enforcement for every lifecycle entity.
- `X-Idempotency-Key` support for payment and booking mutations remains under audit; plot-hold/plot-lock API now requires and honors the key with replay/conflict handling.
- One standard API response envelope across all endpoints.
- Project-level and owner-level query scoping on every request.
- Complete mutation audit records including IP address and before/after payloads.
- AES-256 encryption at rest for customer documents and eKYC identity values is implemented in the Phase 12 document adapter; cloud object storage, pre-signed URLs, and financial-document coverage remain release-hardening work.
- Master-data-backed business enums instead of application hardcoded values.
- Configurable duplicate-match thresholds (95/90/80%) stored as system parameters,
  pending confirmation against the source wireframe.
- DB/distributed-lock concurrency tests for contested plot operations.
- Prometheus-compatible `/metrics` endpoint is implemented with HTTP request counters/latency, DB connection utilization, and queue-depth gauges; production exporter integration remains.
- Required middleware pipeline and greater than 80% core business-logic coverage.

## Open specification decisions

- Under Construction plot status, custom report-builder dimensions, Manager/Site
  Visit Executive dashboard widgets, and drag-and-drop dashboard widgets remain
  open items in the specification.

## Implemented

- GNFR-03/GNFR-13 hardening slice: plot-hold requests require `X-Idempotency-Key`, replay the original response for the same payload, reject payload conflicts, and expose Prometheus-compatible `/metrics` series for request totals/latency, DB utilization, and background queue depth.
- Media test isolation hardening: document and expense upload test suites use temporary `MEDIA_ROOT`, removing local filesystem permission failures from those suites.

- Django/DRF project structure, database migrations, admin configuration, and environment-based settings.
- FR-P0-01/DM-P0-01/DM-P0-02: canonical organization `code`/`status` fields and organization-scoped Project model with name, unique per-organization code, description, status, timestamps, migration-safe legacy organization code population, and Django admin support.
- API-P0-01/API-P0-02: authenticated discovery endpoints return only active organizations and projects available through the user's active organization memberships; users with no assignments receive empty lists.
- API-P0-03/FR-P0-06: organization Admins and Django superusers can create, retrieve, update, and soft-deactivate projects; non-admin creation/modification is forbidden and mutations produce audit records with IP and before/after payloads.
- FR-P0-02/EC-P0-02 foundation: centralized middleware validates `X-Project-ID` on resolved versioned organization APIs and project mutations, attaches the active same-organization project to the request, and rejects missing, inactive, cross-organization, inaccessible, or mismatched contexts before controller mutation. Authentication/404 semantics are preserved; only the project treatment of organization-wide administration/HR/settings records remains to be decided.
- FR-P0-02/GNFR-06 row isolation: a context-local `ProjectScopedModel`/manager automatically binds new request-time rows to the resolved project and filters default querysets to that project. Applied to leads, site visits, telecalling attempts/reminders, inventory, bookings, payments, registry/possession, customer/employee documents, and expenses. Explicit `all_objects` access is reserved for migrations/administration.
- Project-local uniqueness: inventory numbers/codes, document categories/versions, receipts/payment IDs, recently viewed plots, and expense categories may repeat across different projects but remain unique inside one project. Conditional legacy constraints preserve uniqueness for nullable pre-migration rows.
- Operational HR/settings scoping: attendance, leave, holidays, employee activity, master data, integration configurations, system parameters, and audit logs now use the same automatic project boundary. Organization identity/membership/role records and organization profile settings remain shared across projects.
- FR-P2-01/DM-P2-01/DM-P2-02: added canonical project-scoped master-data categories linked to master-data items, automatic category provisioning for existing category-style routes and service-created records, migration-safe backfill for legacy items, category metadata in API responses, category-local duplicate validation, and same-organization cross-project isolation.
- FR-P2-02/EC-P2-01/DM-P2-03: system-parameter reads now use a project-aware Redis-compatible cache-aside service with configurable TTL and negative caching. API create/update/delete operations invalidate the affected key immediately, and the site-visit reminder-days consumer observes an updated value on its next read. Django tests use an isolated in-memory cache while non-test environments retain Redis.
- FR-P2-03: master-data items referenced by system logic carry an API-immutable `is_system` flag. Generic deletion rejects these records with HTTP 409 while `is_active=false` remains allowed. Existing and newly provisioned call dispositions are marked protected, while configurable non-system items retain confirmed hard-delete behavior.
- FR-P2-04: master-data and system-parameter mutation routes now require an organization Admin or platform Super Admin. A Manager remains forbidden even if a generic `settings.edit` permission is manually granted; permitted read access remains independent.
- NFR-P2-01: system-parameter writes now coerce valid string, integer, and finite float values to canonical JSON-safe types, reject malformed/boolean-as-number/non-finite input, and safely convert the existing value when `data_type` changes. Legacy decimal/boolean/JSON types remain supported.
- NFR-P2-02: added an authenticated, organization/project-scoped read-only master-data consumer endpoint at `GET /api/v1/organizations/<slug>/master-data/<category>/`. It is available to assigned non-admin users without Settings permission and returns active items only; inactive and cross-project items are excluded.
- FR-P2-01/GNFR-09 lead-source integration: lead creation and update now validate `source` against active, project-scoped `lead_source` master data instead of Django model choices. Six protected defaults are seeded for existing projects and lazily provisioned for new projects, project-specific custom sources are accepted, and deactivated or cross-project sources are rejected immediately.
- FR-P2-01/FR-P7-04/GNFR-09 site-visit-outcome integration: outcome submission now validates against active, project-scoped `site_visit_outcome` master data instead of Django model choices. The seven specification-defined outcomes are seeded as protected system items for existing projects and lazily provisioned for new projects; active custom outcomes are accepted, while inactive, unknown, and cross-project outcomes are rejected without completing the visit.
- API-P2-03/API-P2-05: canonical `PUT` updates are now supported for master-data items and system parameters in addition to partial `PATCH`. Full replacements retain Admin/Super Admin authorization, serializer validation, audit logging, typed parameter coercion, and immediate parameter-cache invalidation.
- FR-P2-01/FR-P2-03/FR-P8-02/GNFR-09 plot-status integration: the confirmed `Available`, `Blocked`, `Hold`, `Booked`, `Sold`, `Cancelled`, and `Under Construction` statuses are protected project master data. Plot transition and filter inputs require an active current-project status; deactivation is effective immediately, while the guarded lifecycle still rejects invalid jumps. Plot and immutable history fields no longer use Django model choices as input validation.
- FR-P2-01/FR-P5-02 lead-status catalogue: the exact `New → Contacted → Interested → Site Visit Scheduled → Site Visit Completed → Converted / Lost` lifecycle catalogue is seeded as protected project master data and lazily provisioned through the active-only consumer lookup. The Phase 5 transition engine remains Phase 5 scope.
- FR-P2-01 expense-category administration: project-specific expense-category items are supported by the same canonical Admin/Super Admin master-data CRUD and active-only consumer lookup; no default values are hardcoded because the specification defines this as a configurable category without a fixed catalogue.
- FR-P0-05: public `/healthz` liveness and `/readyz` database-readiness endpoints return the standard API envelope and readiness failure returns HTTP 503.
- Token authentication: registration, login, logout, current-user, password change, and password reset flows.
- Organization tenancy, memberships, access scopes, platform access, roles, permissions, and audit foundations.
- Leads, follow-up calls, lead assignment, lead status handling, dashboard, and summary APIs.
- Site visit scheduling, rescheduling, cancellation, executive assignment, outcomes, and visit history.
- FR-P6-01 telecalling queue foundation: `GET /api/v1/organizations/<organization_slug>/telecalling/queue/` returns one current attempt per lead; pending attempts (`called_at IS NULL`) sort first, scheduled follow-ups sort earliest-first, and creation time/ID provide deterministic ties. The endpoint supports `assigned`, `pending`, `connected`, and `follow_ups` tabs, bounded pagination, organization isolation, telecaller-own scoping, and manager/admin team visibility. This now matches the v2.0 rule that lead score is out of scope.
- FR-P6-02 revised external-call model: the obsolete `calls/start` and `calls/end` routes are removed. The model and migration remove `started_at` and `duration_seconds`, and analytics no longer expose timer-derived duration metrics.
- FR-P6-03 master-data dispositions: `GET /api/v1/organizations/<organization_slug>/telecalling/dispositions/` returns the active organization-scoped catalogue in configured order. The fixed codes are `interested`, `callback_later`, `busy`, `no_answer`, `switched_off`, `wrong_number`, `dnd`, and `already_purchased`; defaults are seeded for existing organizations and lazily provisioned for new ones. Call completion accepts only active catalogue values. Codes/names cannot be added or renamed and records cannot be hard-deleted, but administrators may deactivate them.
- FR-P6-04 mandatory disposition validation: API-P6-06 rejects missing, blank, inactive, unknown, and obsolete disposition values without persisting a call log.
- FR-P6-05 conditional follow-up scheduling: API-P6-06 requires a valid ISO-8601 `next_follow_up` in the same submission for Interested and Callback Later; other dispositions may omit it.
- FR-P6-06 Phase 14 reminder handoff: scheduling a follow-up atomically creates or updates one organization-scoped `FollowUpReminder` event with the recipient, due time, event type, and delivery payload. Events remain pending for Phase 14 dispatch; unscheduled dispositions create no reminder, and a reminder-write failure rolls back call completion.
- FR-P6-07 team queue management: `GET /api/v1/organizations/<organization_slug>/telecalling/analytics/` provides managers/admins with tenant-scoped queue, completion, connection, follow-up, disposition, and per-telecaller metrics. `POST .../telecalling/queue/redistribute/` atomically reassigns pending queue items and their leads to an active telecaller in the organization. Telecallers remain restricted to their own queue and are forbidden from team analytics and redistribution.
- API-P6-04 follow-up contract: `POST /api/v1/organizations/<organization_slug>/telecalling/follow-ups/` creates or updates a scheduled follow-up and its reminder event. It rejects call-activity fields so API-P6-06 remains the sole completed-call logging path.
- FR-P6-08 / API-P6-06: `POST /api/v1/organizations/<organization_slug>/telecalling/calls/log/` records a completed external call with `lead_id`, disposition, notes, defaulted/editable call timestamp, optional validated recording, and conditional follow-up. It reuses the caller's pending queue item when available, writes an audit record, and is transactionally coupled to reminder creation.
- Plot blocks, plots, status history, holds, expiry handling, plot selection, bookings, pricing, installments, and possession.
- Payment collection, allocation, receipts, refunds, adjustments, and payment history.
- Agreements and registry tracking, charges, registry history, and registry documents.
- Customer document categories, requirements, uploads, verification history, expiry handling, and organization-scoped downloads.
- Employee profiles, departments, attendance, leave, employee documents, organization holidays, and activity history.
- Expenses, approval steps, payments, reimbursements, categories, reporting, and export endpoints.
- System settings: organization settings, master data, integrations, typed parameters, audit logs, health, maintenance, and backup metadata boundaries.
- FR-P1-05 password reset flow: forgot-password email delivery through the configured backend, reset-token validation, password reset, invalid/expired-token handling, and token-reuse protection are covered by end-to-end API tests using Django's email simulator.
- FR-P1-06 session invalidation: login tracking stores a SHA-256 token hash with IP, user-agent, and expiry metadata; logout revokes the tracked session and DRF token server-side.
- FR-P1-07 route restrictions: unauthenticated requests can reach only login and password-reset endpoints; registration, profile, logout, and change-password endpoints require authentication.
- NFR-P1-01 password hashing: configured Argon2 as the primary Django password hasher and added a regression test confirming passwords are never stored in plaintext.
- NFR-P1-02 OTP storage: added HMAC-SHA256 OTP hashing with constant-time verification, five-minute cache TTL, and one-time consumption through the configured Redis cache backend.
- NFR-P1-03 security tests: added password-hash, OTP expiry/storage, route restriction, session invalidation, and five-failed-login lockout coverage; the fifth failed login returns HTTP 423 with remaining lock time.

## Verification status

- `manage.py check`: passed.
- `makemigrations --check --dry-run`: passed with no pending model changes.
- FR-P6-01 focused suite: 5 tests passed, including queue ordering, latest-attempt de-duplication, role/organization scoping, tabs, pagination, and invalid-query validation.
- Revised FR-P6-02 session-removal suite: verifies the obsolete start/end routes are unavailable and live-session/duration fields are absent.
- FR-P6-03 focused suite: 3 tests passed, covering exact catalogue seeding/listing, tenant isolation, active/inactive validation, unknown-value rejection, and fixed-master mutation protection.
- FR-P6-04 focused suite: validates required active master-data dispositions and confirms rejected submissions persist nothing.
- FR-P6-05 focused suite: covers both conditional dispositions, missing/malformed datetime rejection, persistence, editable timestamps, and unaffected dispositions.
- FR-P6-06 focused suite: covers organization/recipient/payload wiring, no-reminder behavior without a schedule, and transactional rollback on reminder failure.
- FR-P6-07 focused suite: covers tenant-scoped team analytics, per-caller metrics, successful ownership transfer, telecaller authorization denial, and atomic rejection of completed/foreign queue transfers.
- API-P6-04 focused suite: 4 tests passed, covering creation, pending-attempt reuse, conditional scheduling/reminder creation, request validation, assignment scoping, and tenant isolation.
- FR-P6-08/API-P6-06 focused suite: 6 tests passed, covering manual-log happy path, audit logging, disposition/notes validation, conditional follow-up creation, timestamp default/edit behavior, recording validation/upload, authorization, and obsolete-route removal.
- Phase 6 disposition/lifecycle integration suite: 8 manual-call tests passed, covering disposition-driven lead status advancement, valid intermediate transitions, non-regression, follow-up creation, reminder handoff, timestamp, recording, validation, and authorization.
- Leads regression suite: 43 tests passed.
- Phase 0 focused suite: 23 tests passed, including middleware, API row-isolation, automatic project binding, cross-domain manager isolation, project-local uniqueness, and HR/settings isolation coverage. Organization/settings regression suite: 38 tests passed.
- FR-P2-01 focused suite: 4 tests passed, covering canonical category creation/linkage, category-wise create/update, clean duplicate rejection, category-local code reuse, and project isolation. Related settings/Phase 0/call-disposition regression suite: 36 tests passed.
- FR-P2-02 focused suite: 4 tests passed, covering cache reuse, per-project cache separation, create/update/delete invalidation, negative-cache invalidation, and immediate site-visit consumer refresh. Related settings/Phase 0/site-visit/reminder regression suite: 46 tests passed.
- FR-P2-03 focused master-data suite: 7 tests passed, including protected delete rejection, allowed deactivation, immutable protection metadata, normal-item deletion, and call-disposition protection. Related settings/Phase 0/call-disposition regression suite: 43 tests passed.
- FR-P2-04 focused suite: 3 tests passed, covering Admin/Super Admin success, non-admin read preservation, and create/update/delete denial even after granting `settings.edit`. Related Phase 2/settings/Phase 0/call-disposition regression suite: 46 tests passed.
- NFR-P2-01 focused suite: 3 tests passed, covering canonical coercion, malformed/boolean/non-finite rejection, datatype-only conversion, and failed-update persistence. Related settings/Phase 2/site-visit/Phase 0 suite: 52 tests passed.
- NFR-P2-02 focused suite: 3 tests passed, covering active-only non-admin lookup, project isolation, unknown categories, unauthenticated access, and organization-access denial. Related settings/Phase 2/call-disposition/Phase 0 suite: 52 tests passed.
- FR-P2-01/GNFR-09 lead-source focused suite: 5 tests passed, covering protected default seeding, custom project sources, active-only create/update validation, removal of model-choice enforcement, and cross-project rejection. Related leads/settings/project-scope regression suite: 91 tests passed.
- FR-P2-01/FR-P7-04/GNFR-09 site-visit-outcome focused suite: 5 tests passed, covering protected default seeding, active custom outcomes, inactive/unknown rejection, cross-project isolation, model-choice removal, and no mutation on invalid input. Related leads/settings/project-scope regression suite: 96 tests passed.
- API-P2-03/API-P2-05 PUT contract tests: 2 tests passed, including full replacement, typed coercion, and immediate cache refresh.
- Plot-status master-data focused suite: 4 tests passed; inventory lifecycle/booking/bulk/history plus Phase 2 regression suite: 59 tests passed.
- Consolidated Phase 2 backend acceptance suite: 64 tests passed, covering master CRUD, system parameters, authorization, protection, project isolation, typed values, cache invalidation, active-only consumers, lead sources, call dispositions, site-visit outcomes, plot statuses, lead statuses, and expense-category lookup behavior. Migration-state and Django system checks passed.
- Latest full backend suite (2026-09-20): 231 tests ran; 226 passed and the same 5 pre-existing document/expense upload tests errored because the local `media/` directory is not writable (2 document tests, 3 expense tests). There were no assertion failures or Phase 2/Phase 3/Phase 4/Phase 5/Phase 6/Phase 7/Phase 8/Phase 9/Phase 10/Phase 11/Phase 12 regressions.
- FR-P1-05 focused suite: 5 tests passed.
- FR-P1-06 focused suite: 2 tests passed.
- FR-P1-07 focused suite: 2 tests passed.
- NFR-P1-01/NFR-P1-02 focused suite: 3 tests passed.
- NFR-P1-03 focused suite: 5 tests passed; users security suite: 14 tests passed.
- Phase 3 focused suite: 5 tests passed, covering project-scoped user assignment, custom-role permission updates with before/after/IP audit data, system-role protection, deactivated-account blocking, and next-request permission revocation.
- Phase 3 regression suite: 62 tests passed across organization, employee, tab-permission, settings, and Phase 2 behavior.
- Phase 4 focused suite: 5 tests passed, covering phone normalization, 95/90/80 duplicate scoring, manual duplicate warning, asynchronous CSV batch/error reporting, Meta redelivery idempotency, and Admin/Manager import-sync authorization.
- Phase 4 leads regression suite: 58 tests passed.
- Phase 5 focused suite: 6 tests passed, covering lifecycle transitions, invalid-transition rejection, immutable status history, mandatory assignment reasons, assignment history, multi-clause filtering/pagination/sorting/tags, transactional bulk actions, converted-lead immutability, and owner-only editing.
- Phase 5 leads regression suite: 64 tests passed.
- Phase 7 focused suite: 6 tests passed, covering executive conflict detection, active-lead scheduling, configurable future-day limits, visit lifecycle rejection, completion score/status integration, and executive-owned visibility.
- Phase 7 leads regression suite: 72 tests passed.
- Phase 8 focused suite: 3 tests passed, covering Site Visit Executive hold-only RBAC, expired-hold auto-release with audit history, and 50 parallel hold requests with exactly one winner.
- Phase 9 focused suite: 5 tests passed for idempotency replay/conflict, configurable minimum payment and expiry, atomic rollback, eKYC/qualification gating, and sequential PDF receipts. The missing auth schema migration was generated/applied (`auth.0013_user_middle_name_user_title`); `auth_user` now contains both columns. Full backend suite: 219 tests ran, 214 passed, with 5 pre-existing media-permission errors in document/expense upload tests.
- Phase 10 focused suite: 4 tests passed for lead-conversion customer creation, duplicate phone/email/government-ID blocking, non-destructive status updates, assigned telecaller visibility, notes, and 360 aggregation. Related Phase 5 lead regression plus Phase 9 booking suite: 11 tests passed. Customer migrations applied successfully.
- Phase 11 focused suite: 4 tests passed for payment idempotency replay/conflict, immutable payment/allocation rows, exact overdue/advance calculations, cheque/payment controls, and Admin-only refund approval. Phase 9 + Phase 10 + Phase 11 combined suite: 13 tests passed. Inventory regression suite: 52 tests passed. Payment migration `inventory.0017_payment_controls` applied successfully.
- Phase 12 focused suite: 4 tests passed for encrypted-at-rest uploads, expiry notification outbox creation, encrypted eKYC identity verification, provider-outage retry processing, and telecaller eKYC denial. Migration `documents.0006_documentexpirynotification_ekycverification` plus metadata migration `documents.0007_phase12_model_metadata` applied successfully.
- Phase 15 focused suite: 4 tests passed for working-hours calculation, overlapping-leave rejection without duplicate rows, leave-balance deduction on approval, and manager-only quarterly performance reviews. Organization/HR regression suite: 41 tests passed. Migration `organizations.0015_phase15_hrms` applied successfully.
- Phase 13 focused suite: 5 tests passed for unpaid/eKYC/legal-document registry gates, charge calculation, and cancellation returning the plot to `Booked`. Phase 5 registry regression: 3 tests passed after aligning the legacy fixture with the Phase 13 cross-phase gates.
- Phase 16 focused suite: 3 tests passed for threshold-based receipt enforcement, approved-record immutability, and Admin-only cancellation. Existing Expenses suite: 18 tests passed with temporary media-root isolation; no new migration was required.
- Inventory regression suite: 43 tests passed.

## Known gaps and risks

- Customer identity/lifecycle needs a clear canonical model and consistent links across leads, bookings, payments, and documents.
- Provider integrations are not complete: Meta/Google lead sync, WhatsApp, SMS, email automation, and eKYC require confirmed contracts and credentials. Telephony integration is not required because Phase 6 calls occur outside the system.
- Communications automation and notification triggers are not complete.
- Loans has no complete backend domain workflow and requires a scope decision.
- Some authorization paths and domain workflows require final cross-module isolation and permission testing.
- Backup/restore, deployment, monitoring, and production operational procedures require release hardening.

## Immediate next steps

1. Finish common API response-envelope migration and complete audit-interceptor coverage with explicit before/after payload fields.
2. Complete payment/booking idempotency audit and owner-level authorization matrix.
3. Investigate the existing Phase 11 overdue-refresh regression and run a fresh full-suite baseline.
4. Add a route/API and domain coverage matrix and verify >80% core-service coverage.
5. Complete real provider integrations only after their credentials and failure behavior are defined.

## Release definition

Backend functionality is considered release-ready only when it has a migration,
service-level rules, permission and organization-isolation checks, API tests,
documented endpoints, and a connected frontend workflow where applicable.
