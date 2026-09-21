# Project Implementation Phases

## 1. Executive Summary

This document structures the greenfield project into 17 logical development phases [31, 32].

The CRM spans 19 core functional modules—from multi-channel lead acquisition and telecalling queues to plot inventory blocking, booking management, eKYC verification, multi-mode payment collection, registry tracking, employee management (mini-HRMS), expenses approvals, and automated notifications [1, 2, 3, 4, 5, 7, 8, 10, 12, 14, 15, 16, 19, 20, 21, 22, 23, 24].

### Phase Summary Table

| Phase | Name | Main Objective | Dependencies | Priority | Complexity |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase 0** | Project Foundation & Shell | Setup tech stack, DB schemas, global app shell, navigation, & state [12, 28] | None | Critical | Medium |
| **Phase 1** | Authentication & RBAC | Secure access, role-based routing, JWT/sessions, password recovery [1] | Phase 0 | Critical | Medium |
| **Phase 2** | Project Context & Admin Setup | Organization/Project context switcher, master data, system parameters [12, 14] | Phase 1 | Critical | Medium |
| **Phase 3** | User & Role Administration | Manage system users, grant granular module/field permissions, audit logs [14] | Phase 2 | Critical | Medium |
| **Phase 4** | Lead Acquisition & Multi-Channel Sync | Meta/Google Ads sync, manual creation, CSV import, duplicate detection [19] | Phase 3 | Critical | High |
| **Phase 5** | Lead Management & Lifecycle | Lead qualification, status transitions, assignment/reassignment, filters [20] | Phase 4 | High | Medium |
| **Phase 6** | Telecalling & Calling Queue | Call queue assignment, active call panel, dispositions, follow-up scheduler [21] | Phase 5 | High | High |
| **Phase 7** | Site Visit Management | Schedule visits, executive assignment, calendar/list views, visit outcomes [22] | Phase 5 | High | Medium |
| **Phase 8** | Plot Inventory & Layout Interaction | Plot status lifecycle (Available/Hold/Blocked), interactive map layout [23, 24] | Phase 2 | Critical | High |
| **Phase 9** | Booking Management Workflow | Real-time plot selection, hold periods, booking creation, receipt generation [2] | Phase 5, 8 | Critical | Very High |
| **Phase 10** | Customer Management & 360° Profile | Profile creation, activity timeline, linked bookings/payments/docs [3] | Phase 9 | High | Medium |
| **Phase 11** | Payment Management & Ledger | Payment collection (UPI, Card, Cash, Cheque), dues tracking, ledger, refunds [4] | Phase 9, 10 | Critical | Very High |
| **Phase 12** | Documents & eKYC Verification | Secure storage, document category validation, Aadhaar/PAN eKYC API [5] | Phase 10 | High | High |
| **Phase 13** | Registry Management & Sale Deed | Track registry dates, legal/stamp charges calculation, sale deed status [7] | Phase 9, 11, 12 | Medium | Medium |
| **Phase 14** | Communication & Auto-Triggers | Multi-channel engine (WhatsApp, SMS, Email), templates, auto-rules [10] | Phase 2, 5, 9 | High | High |
| **Phase 15** | Employee Management (Mini-HRMS) | Central HR profiles, attendance check-in/out, leave approvals, reviews [8, 15] | Phase 3 | Medium | Medium |
| **Phase 16** | Expenses Tracker & Approvals | Expense entry, bill attachments, manager approval workflow, reimbursements [9, 16] | Phase 3, 15 | Medium | Medium |

---

## 2. Source Analysis

The source material comprises 25 technical artifacts [1-25]:
1. **Wireframe Artifacts (Parts 01 to 21)** [1-24]: Low-fidelity visual specifications, component states, navigation maps, permission tables, business rules, edge cases, and user journeys across 21 functional domain modules.
2. **Technical Execution Specification (`prompt.md`)** [25-45]: Guidance detailing engineering standards, dependency rules, risk analysis criteria, and output formatting.

### Source Mapping & Coverage

- **Part 01 (Authentication & Access)** [1]: Login (Email/Phone/OTP), Forgot/Reset Password, 403 Access Denied, Session Timeout, Logout, Role Access Overview.
- **Part 02 (Organisation / Project Context + Global Application Shell)** [12]: Project Selector Dropdown, Add Project Modal, Global Search, Notifications Drawer, Profile Menu, Unsaved Changes Guard, Breadcrumbs.
- **Part 04 (Lead Acquisition)** [19]: Meta Ads API sync, Google Ads API sync, Manual Creation Form, CSV Drag-and-Drop Import with field mapping, and weighted Phone+Email Duplicate Detection (95%, 90%, 80% confidence matching).
- **Part 05 (Lead Management)** [20]: Lead table with multi-filters, detail slide-over, status lifecycle (New -> Contacted -> Interested -> Site Visit Scheduled -> Site Visit Completed -> Converted / Lost), assign/reassign modal, bulk operations.
- **Part 06 (Telecalling)** [21]: Calling Queue, Active Call Screen with timer and mute/hold, Call Outcomes (Interested, Callback, Busy, No Answer, DND, etc.), Follow-up Scheduler, and Call History.
- **Part 07 (Site Visit Management)** [22]: Month/List Calendar views, Schedule/Reschedule/Cancel Modals, Executive Assignment, No-Show tracking, 1-5 Star Interest Rating, and Visit Outcome logs.
- **Part 08 & Part 09 (Plot Inventory & Selection Interaction)** [23, 24]: Plot Inventory Table, Plot Status Lifecycle (Available, Blocked/Hold, Booked, Sold, Under Construction, Cancelled), Grid Layout Visualizer, Block/Hold Modal with countdown timer, Conflict Resolution Modal on real-time re-check.
- **Part 10 (Booking Management)** [2]: Booking Creation Flow (Select Customer -> Select Plot -> Booking Details -> Payment -> Confirmation), Hold Expiry Timer, Booking Status Lifecycle, Booking Receipt Generator.
- **Part 11 (Customer Management)** [3]: 360° Customer Profile, Status Lifecycle (New -> Active -> Engaged -> Converted -> Inactive / Blacklisted), Activity Timeline, Linked Modules Summary (Leads, Site Visits, Bookings, Payments, Documents).
- **Part 12 (Payment Management)** [4]: Payment Collection against single/multiple dues, Dues Calculation Engine, Payment Modes (UPI, Card, Cash, Cheque, Net Banking), Payment Ledger, Receipt Generation, Refund/Adjustment Approval Flow.
- **Part 13 (Documents & eKYC Management)** [5]: Document Category Repository, File Upload with format/size rules, eKYC Integration (Aadhaar UIDAI, PAN NSDL, Face Match), Document Expiry Tracker, Pending Approval Queue.
- **Part 15 / Part 16 (Employee Management / Mini-HRMS)** [8, 15]: Employee Directory, Add/Edit Profile, Job Info, Attendance Check-In/Out, Leave Requests & Approvals, Quarterly Performance Reviews.
- **Part 16 / Part 17 (Expenses Tracker)** [9, 16]: Expense Logging, Category Management, Receipt Attachment, Manager Approval/Rejection Workflow, Payment/Reimbursement Status.
- **Part 15 (Registry Management)** [7]: Plot Registry Tracking, Sub-Registrar Details, Charges Breakdown (Stamp Duty, Registration, Legal Fees, TDS), Document Uploads, Registry History.
- **Part 18 (Communication & Notifications)** [10]: WhatsApp, SMS, Email Channels, Pre-approved Template Builder, Variable Substitution, Communication Logs, Trigger Rules (e.g., Payment Due 3 Days Before).
- **Part 21 (Settings & Administration)** [14]: General Settings, User Directory, Roles & Permissions Matrix, Master Data Manager, Integration Keys, System Parameters, Audit Logs, Database Backup & Maintenance.

---

## 3. Current System Status

### Implemented
- **None**: The system is a greenfield project [25, 28]. All architecture, backend APIs, frontend interfaces, and database schemas must be constructed from the low-fidelity UX wireframes [1-24].

### Partially Implemented
- **None**.

### Not Implemented
- **All 21 Functional Modules**:
  1. Authentication & Access Control [1]
  2. Organisation / Project Shell & Global Navigation [12]
  3. Role-Based Access Control (RBAC) Engine [14]
  4. Lead Acquisition (Meta/Google Ads & CSV Import) [19]
  5. Lead Qualification & Lifecycle Management [20]
  6. Telecalling Queue & Disposition Tracker [21]
  7. Site Visit Scheduling & Execution [22]
  8. Plot Inventory Management & Interactive Layout Map [23, 24]
  9. Booking Management & Real-Time Hold Locking [2]
  10. 360° Customer Profile Management [3]
  11. Multi-Mode Payment Collection & Ledger [4]
  12. Document Management & Third-Party eKYC Verification [5]
  13. Registry & Sale Deed Tracking [7]
  14. Employee Management (Mini-HRMS) [8, 15]
  15. Expenses Tracker & Reimbursements [9, 16]
  16. Multi-Channel Communication Engine (WhatsApp, SMS, Email) [10]
  17. Automated Trigger & Notification System [10]
  21. Audit Logging & System Maintenance Utilities [14]

### Needs Verification
- **Filenames Marked `_not_implementing.png`**: Source images `ShrijidevelopersCRMUXandlowfedUI (15)_not_implementing.png` (Registry Management) [7] and `ShrijidevelopersCRMUXandlowfedUI (17)_not_implementing.png` (Expenses Tracker) [9] carry filenames indicating they might be excluded or updated by other parts. However, functional requirements for Registry Management (Part 15) [7] and Expenses Tracker (Part 16/17) [9, 16] are fully articulated in the wireframe sheets. We have included them as distinct phases (Phase 13 & Phase 16) but flagged them for explicit client confirmation before sprint execution [27, 38].
- **Tech Stack Confirmation**: UX wireframes prescribe visual flows, validation rules, and business logic, but do not constrain programming languages or frameworks. We recommend a robust modern stack (e.g., PostgreSQL, Node.js/TypeScript or Python/FastAPI, Next.js/React, Tailwind CSS, Redis) [42, 44].

---

## 4. Complete Requirements

The complete system requirements extracted from the wireframes [1-24] are categorized below:

### 1. Authentication & Authorization
- Secure login using Email/Phone + Password or 6-digit OTP [1].
- Account lockout after 5 consecutive failed attempts for 15 minutes [1].
- Inactivity session timeout after 30 minutes (configurable) [1].
- Role-Based Access Control (RBAC) with granular permissions (View, Create, Edit, Delete, Export, Approve) across all modules [1, 14].

### 2. Organization & Global App Shell
- Multi-project / multi-organization context switching via dropdown header [12].
- Global layout featuring collapsible sidebar, top bar search, notification drawer, profile dropdown, and breadcrumb tracking [12].
- Unsaved changes route guard and restricted navigation modals [12].

### 3. Lead Acquisition & Management
- Automated background sync for Meta Ads and Google Ads leads [19].
- Drag-and-drop CSV lead import with field mapping, error highlighting, and summary report [19].
- Automated phone + email duplicate detection with match confidence scoring (95% exact, 90% partial, 80% name match) [19].
- Lead lifecycle stages: New -> Contacted -> Interested -> Site Visit Scheduled -> Site Visit Completed -> Converted / Lost [20].
- Bulk lead assignment, status update, tagging, and CSV/Excel export [20].

### 4. Telecalling Operations
- Dynamic calling queue ordered by priority, assigned owner, and scheduled call time [21].
- Active Call Panel with live timer, call controls (Mute, Hold), quick note taker, and disposition selector [21].
- Disposition outcomes: Interested, Callback Later, Busy, No Answer, Switched Off, Wrong Number, DND, Already Purchased [21].
- Automated follow-up task creation linked to leads [21].

### 5. Site Visit Management
- Site visit calendar (Month view) and upcoming visits list view [22].
- Executive assignment, meeting point capture, and customer plot preferences [22].
- Outcome submission: 1-5 star interest level, feedback categories (Price, Location, Loan, etc.), and no-show marking [22].

### 6. Plot Inventory & Selection
- Plot status states: Available, Blocked/Hold, Booked, Sold, Under Construction, Cancelled [23].
- Interactive map/grid layout with color-coded status legend [24].
- Temporary plot blocking/holding with automated countdown timer and expiry [23, 24].
- Pre-booking availability re-check with concurrency conflict modal [24].

### 7. Booking Management
- End-to-end booking flow: Customer Selection -> Plot Selection -> Pricing Details -> Payment -> Confirmation [2].
- PLC (Preferential Location Charges), discount handling, and net price calculation [2].
- Non-refundable booking hold policy enforcement [2].
- Printable booking summary and payment receipt generation [2].

### 8. Customer Management (360° Profile)
- Single customer profile consolidating contact details, status (New, Active, Engaged, Converted, Inactive, Blacklisted) [3].
- Unified timeline linking leads, site visits, bookings, payments, uploaded documents, and communication logs [3].

### 9. Payment Management & Ledger
- Multi-mode payment collection: Cash, UPI, Credit/Debit Card, Bank Transfer (NEFT/RTGS), Cheque [4].
- Multi-due selection enabling payment against booking amount, site visit fees, maintenance, or legal charges [4].
- Automated customer ledger generation (Total Dues, Total Paid, Outstanding Balance) [4].
- Role-based refund and payment adjustment approval workflow [4].

### 10. Documents & eKYC Verification
- Secure document repository supporting PDF, PNG, JPG (max 10MB) [5].
- Document categories: ID Proof, Address Proof, Financial, eKYC Documents [5].
- Third-party eKYC integration: Aadhaar (UIDAI), PAN (NSDL), Address verification, Face Match score [5].
- Document expiry tracking with automated email/SMS reminders [5].

### 11. Registry Management
- Registry process tracking: Pending -> In Process -> Completed / Cancelled [7].
- Cost calculator for Stamp Duty, Registration Fees, Legal Fees, TDS, and Net Consideration Amount [7].

### 12. Employee Management (Mini-HRMS)
- Central employee directory with personal, job, salary, and reporting structure info [8, 15].
- Daily attendance check-in/check-out tracking [15].
- Leave request management (Casual, Sick, Paid) with manager approval workflow [15].
- Quarterly performance review logs [15].

### 13. Expenses Tracker
- Expense logging with mandatory category selection and receipt proof upload [9, 16].
- Multi-level approval workflow (Submitted -> Pending Approval -> Approved/Rejected -> Reimbursed) [9, 16].

### 14. Communication Engine & Notifications
- Multi-channel messaging: WhatsApp Business API, SMS Gateway (MSG91), SMTP Email [10].
- Template manager with variable insertion (`{customer_name}`, `{plot_no}`, `{due_amount}`) [10].
- Trigger rules for automated alerts (Lead Assignment, Site Visit Reminder, Payment Due, Document Expiry) [10].

### 15. System Settings
- Role-specific dashboards (Super Admin, Manager, Telecaller, Site Exec, Accounts) with drag-and-drop widgets [11, 18].
- System settings: Company profile, master data lists, parameter configs, audit log viewer, DB backup controls [14].

---

## 5. System Architecture Understanding

```text
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                FRONTEND APPLICATION LAYER                               │
│  ┌───────────────────────┐  ┌─────────────────────────┐  ┌───────────────────────────┐  │
│  │   (Next.js / React)   │  │   (Recharts / Widgets)  │  │   (Canvas / SVG Grid)     │  │
│  └───────────┬───────────┘  └────────────┬────────────┘  └─────────────┬─────────────┘  │
└──────────────┼───────────────────────────┼─────────────────────────────┼────────────────┘
               │                           │                             │
               ▼                           ▼                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   API GATEWAY & ROUTING                                 │
│       [ JWT / Session Auth ]  ───  [ RBAC Guard ]  ───  [ Rate Limiter & Audit Log ]     │
└──────────────────────────────────────────┬──────────────────────────────────────────────┘
                                           │
                                           ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                  BACKEND SERVICES LAYER                                 │
│  ┌───────────────────────────────┐  ┌───────────────────────────────┐                   │
│  │ Auth & Identity Service       │  │ Lead & Telecalling Service    │                   │
│  ├───────────────────────────────┤  ├───────────────────────────────┤                   │
│  │ Project Context Service       │  │ Site Visit Management Service │                   │
│  ├───────────────────────────────┤  ├───────────────────────────────┤                   │
│  │ Plot Inventory Engine (Redis) │  │ Customer & 360 Timeline Svc   │                   │
│  ├───────────────────────────────┤  ├───────────────────────────────┤                   │
│  │ Booking & Lock State Manager  │  │ Payment & Financial Ledger    │                   │
│  ├───────────────────────────────┤  ├───────────────────────────────┤                   │
│  │ Document & eKYC Service       │  │ Registry & Legal Service      │                   │
│  ├───────────────────────────────┤  ├───────────────────────────────┤                   │
│  │ Communication & Alert Worker  │  │ HRMS & Expense Service        │                   │
│  └───────────────────────────────┘  └───────────────────────────────┘                   │
└──────────────────────────────────────────┬──────────────────────────────────────────────┘
                                           │
                                           ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                 DATA & PERSISTENCE LAYER                                │
│  ┌───────────────────────────────┐  ┌───────────────────────────────┐                   │
│  │ Primary RDBMS (PostgreSQL)    │  │ Redis Cache & Lock Manager    │                   │
│  │ (ACID Transactions / Ledger)  │  │ (Plot Hold TTLs / Call Queue) │                   │
│  ├───────────────────────────────┤  ├───────────────────────────────┤                   │
│  │ Cloud Storage (AWS S3)        │  │ Third-Party Integration APIs  │                   │
│  │ (Encrypted Documents & Bills) │  │ (eKYC, Payment, SMS, WhatsApp)│                   │
│  └───────────────────────────────┘  └───────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

The system requires an architecture capable of strict financial integrity and high concurrency handling [28, 44]:
1. **State Locking for Plot Inventory**: Plot selection and holding require optimistic or distributed locks (via Redis or PostgreSQL `SELECT FOR UPDATE`) to eliminate double-booking during concurrent executive requests [23, 24].
2. **Financial Ledger Double-Entry Rules**: Payments and dues must maintain strict relational integrity with transaction logs; editing past payments is disallowed—only reverse/adjustment entries are permitted [4, 12].

---

## 6. Dependency Analysis

```text
Authentication [1]
      ↓
Global Shell & Project Context [12]
      ↓
Users & Roles Administration (RBAC) [14]
      ↓
Master Data & System Settings [14]
      │
      ├───────────────────────────────┐
      ▼                               ▼
Plot Inventory Management [23, 24]  Lead Acquisition & Sync [19]
      │                               │
      │                               ▼
      │                             Lead Management [20]
      │                               │
      │                               ├───────────────────────────────┐
      │                               ▼                               ▼
      │                             Telecalling Queue [21]         Site Visit Management [22]
      │                               │                               │
      └───────────────────────────────┴───────────────┬───────────────┘
                                                      │
                                                      ▼
                                           Booking Management [2]
                                                      │
                                                      ▼
                                           Customer Management (360°) [3]
                                                      │
                                                      ├───────────────────────────────┐
                                                      ▼                               ▼
                                           Payment Management [4]          Documents & eKYC [5]
                                                      │                               │
                                                      └───────────────┬───────────────┘
                                                                      │
                                                                      ▼
                                                           Registry Management [7]
                                                                      │
      ┌───────────────────────────────────────────────────────────────┤
      ▼                                                               ▼
Employee Management (Mini-HRMS) [8, 15]                      Communication & Auto-Triggers [10]
      │                                                               │
      ▼                                                               │
Expenses Tracker [9, 16]                                             │
      │                                                               │
      └───────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
                                      │
                                      ▼
```

### Core Dependency Rules
1. **Auth & RBAC First**: No functional domain (Leads, Plots, Payments) can be implemented without Auth [1], Project Context [12], and RBAC permissions [14] established.
2. **Inventory + Lead -> Booking**: Booking Management [2] requires both Plot Inventory [23, 24] and an existing qualified Lead/Customer record [20].
3. **Booking -> Customer + Payment**: Payment collection [4] and eKYC [5] depend on an active Booking [2] and Customer profile [3].
4. **Payment + eKYC -> Registry**: Registry tracking [7] requires fully paid booking dues [4] and verified customer eKYC documents [5].

---

## 7. Phase Overview

The project is structured into 17 discrete phases [31, 32]:
- **Phase 0**: Project Foundation, Architecture & Global Application Shell
- **Phase 1**: Authentication, Session Management & Security Guards
- **Phase 2**: Project Context Engine & Master Data Administration
- **Phase 3**: Role-Based Access Control (RBAC) & User Management
- **Phase 4**: Lead Acquisition, CSV Parser & Ad Network Integrations
- **Phase 5**: Lead Lifecycle, Qualification & Assignment Engine
- **Phase 6**: Telecalling Operations & Dynamic Call Queue
- **Phase 7**: Site Visit Scheduling, Executive Mapping & Outcome Tracking
- **Phase 8**: Plot Inventory Management & Interactive Layout Map
- **Phase 9**: Real-Time Booking Management & Concurrency Holding
- **Phase 10**: Customer 360° Profile & Interaction Timeline
- **Phase 11**: Multi-Mode Payment Collection, Dues & Financial Ledger
- **Phase 12**: Document Repository & Third-Party eKYC Verification
- **Phase 13**: Registry Management & Sale Deed Process Tracking
- **Phase 14**: Multi-Channel Communication Engine & Notification Rules
- **Phase 15**: Employee Management & Mini-HRMS
- **Phase 16**: Expenses Tracker, Bill Verification & Approval Workflow

---

## 8. Phase 0 — Project Foundation & Application Shell

### Objective
Establish the core repository structure, database connection pooling, global application shell, header, sidebar navigation, and route protection infrastructure [12, 28].

### Business Purpose
Provide users across all organizational roles with a unified, responsive interface and navigation framework, enabling seamless project switching and context awareness [12].

### Features Included
- Repository and environment bootstrap.
- Global Application Shell (Top Bar, Collapsed/Expanded Sidebar, Footer) [12].
- Project / Organization Context Selector [12].
- Global Search Bar interface [12].
- Notifications Drawer & Profile Dropdown UI [12].
- Unsaved Changes Guard modal [12].
- Restricted Route Modal [12].

### Backend Work
- Base API framework configuration (routing, error handling middleware, request logger).
- Environment variable configuration.
- Health check endpoints (`/healthz`, `/readyz`).
- Project Context middleware (reading `X-Project-ID` header).

### Frontend Work
- Layout wrapper component (`GlobalAppShell`) [12].
- Sidebar navigation tree rendering based on role routes [12].
- Header components: `ProjectSelector`, `GlobalSearchInput`, `Notification Bell`, `ProfileMenu` [12].
- UI Modals: `UnsavedChangesModal`, `RestrictedAccessModal` [12].
- Breadcrumb tracking system [12].

### Dependencies
```text
Depends on:
- None (Initial Phase)
```

### Database Impact
- **New Table**: `organizations` (`id`, `name`, `code`, `status`, `created_at`).
- **New Table**: `projects` (`id`, `organization_id`, `name`, `code`, `description`, `status`, `created_at`).

### API Impact
```text
New APIs:
- GET /api/v1/organizations
- GET /api/v1/projects
- POST /api/v1/projects
```

### Authorization / Roles
- All authenticated users can view the shell and switch projects assigned to them [12].
- Super Admin / Admin can create new projects [12, 14].

### Business Rules
- Switching projects reloads the active project context across all dashboard widgets and module tables [12].
- Navigating away with dirty form state triggers the `UnsavedChangesModal` [12].

### Edge Cases
- User has no assigned projects -> Show `NoAccessProject` empty state screen [12].
- Project context expires during active form submission -> Prompt project re-selection [12].

### Testing Requirements
- Unit tests for project context state provider.
- E2E tests for navigation drawer collapse/expand and breadcrumb updates.

### Completion Criteria
```text
Phase is complete when:
- Global shell renders correctly across desktop and mobile viewports.
- Project selector updates application state without full page refresh.
- Unsaved changes modal successfully intercepts route changes.
```

---

## 9. Phase 1 — Authentication & Access Control

### Objective
Implement secure authentication workflows including email/phone login, 6-digit OTP validation, password reset flow, and session management [1].

### Business Purpose
Protect real estate data and customer personally identifiable information (PII) through authenticated, encrypted access control [1].

### Features Included
- Login Page (Email/Phone + Password) [1].
- OTP Verification Flow (6-digit, 5-min expiry) [1].
- Forgot Password & Reset Password Modals [1].
- Access Denied (403) & Session Expired Pages [1].
- Logout confirmation modal [1].

### Backend Work
- Auth endpoints with JWT issue/refresh logic.
- Password hashing (bcrypt / Argon2).
- OTP generation and verification service with Redis key expiration.
- Account lock service (5 failed attempts = 15-min lock).
- Session timeout middleware (30 mins inactivity).

### Frontend Work
- Login screen component (`1.1 Login - Email/Phone`) [1].
- OTP input component (`1.2 Login - OTP Verification`) [1].
- Forgot/Reset password screens (`1.3`, `1.4`) [1].
- Session expired and access denied full-page views (`1.5`, `1.6`) [1].

### Dependencies
```text
Depends on:
- Phase 0 (Global Shell)
```

### Database Impact
- **New Table**: `users` (`id`, `email`, `phone`, `password_hash`, `status`, `failed_attempts`, `locked_until`, `last_login_at`).
- **New Table**: `user_sessions` (`id`, `user_id`, `token_hash`, `ip_address`, `user_agent`, `expires_at`).

### API Impact
```text
New APIs:
- POST /api/v1/auth/login
- POST /api/v1/auth/verify-otp
- POST /api/v1/auth/forgot-password
- POST /api/v1/auth/reset-password
- POST /api/v1/auth/logout
```

### Authorization / Roles
- Unauthenticated users can access login and reset routes [1].
- Authenticated users can log out and request password updates [1].

### Business Rules
- Passwords must contain minimum 8 characters, with letters, numbers, and symbols [1].
- OTP expires in exactly 5 minutes [1]. Account locks for 15 minutes after 5 consecutive failures [1].

### Edge Cases
- OTP requested multiple times rapidly -> Rate limit OTP generation (max 3 requests / 10 mins).
- User attempts to log in while account is locked -> Return error showing remaining lock time.

### Testing Requirements
- Unit tests for password hash validation and OTP expiration logic.
- Integration test for 5 failed logins resulting in 423 Locked state.

### Completion Criteria
```text
Phase is complete when:
- User can log in with valid credentials and receive secure JWT tokens.
- Invalid logins trigger error states and rate locks correctly.
- Password reset token flow functions end-to-end via email/SMS simulator.
```

---

## 10. Phase 2 — Project Context & Master Data Administration

### Objective
Provide administrative screens and database models for project management, master data lookup values, and system parameters [12, 14].

### Business Purpose
Standardize system-wide dropdown choices (lead sources, plot statuses, expense categories) and business parameter threshold settings across projects [14].

### Features Included
- Project creation and configuration modal [12].
- Master Data administration interface (Plot Statuses, Lead Statuses, Lead Sources, Expense Categories) [14].
- System Parameters configuration screen (Reminder days, auto-logout timer, minimum advance payment percentage) [14].

### Backend Work
- Master Data CRUD services.
- System Parameters cache-aside manager (stored in DB, cached in Redis).
- Validation schemas for parameters.

### Frontend Work
- Project Creation form (`1.2 Add New Project`) [12].
- Master Data table and editor (`8. Master Data Page`) [14].
- System Parameters form (`10. System Parameters Page`) [14].

### Dependencies
```text
Depends on:
- Phase 1 (Authentication)
```

### Database Impact
- **New Table**: `master_data_categories` (`id`, `code`, `name`).
- **New Table**: `master_data_items` (`id`, `category_id`, `key`, `value`, `color_code`, `is_active`).
- **New Table**: `system_parameters` (`id`, `project_id`, `param_key`, `param_value`, `data_type`).

### API Impact
```text
New APIs:
- GET /api/v1/master-data/:category
- POST /api/v1/master-data
- PUT /api/v1/master-data/:id
- GET /api/v1/system-parameters
- PUT /api/v1/system-parameters
```

### Authorization / Roles
- Only Super Admin and Admin can edit master data and system parameters [14].

### Business Rules
- System master data keys used in logic (e.g., plot status `AVAILABLE`) cannot be deleted, only deactivated [14].

### Edge Cases
- Admin changes `site_visit_reminder_days` -> Parameter updates instantly in cache for upcoming jobs.

### Testing Requirements
- Unit test for system parameter type conversion (string to int/float).
- API test for master data lookup endpoint.

### Completion Criteria
```text
Phase is complete when:
- Master data lists render dynamically across backend validation and frontend dropdowns.
- System parameters update and persist accurately per project.
```

---

## 11. Phase 3 — Role-Based Access Control (RBAC) & User Administration

### Objective
Build complete user management, custom role creation, granular module-level permission mapping, and audit logging [14].

### Business Purpose
Ensure strict privilege separation so Telecallers, Site Visit Executives, Managers, and Accounts staff only see data permitted by their job duties [1, 14].

### Features Included
- User Directory List with status toggle [14].
- Add / Edit User Modal with role assignment [14].
- Roles & Permission Matrix Page (View, Create, Edit, Delete, Export checkboxes) [14].
- Audit Logs viewer table [14].

### Backend Work
- RBAC permission evaluation middleware (`hasPermission('leads', 'create')`).
- User Management CRUD service.
- Audit Logging interceptor capturing HTTP method, route, user ID, IP address, and payload diff [14].

### Frontend Work
- User Management Page (`5. User Management Page`) [14].
- Roles & Permissions Editor (`6. Roles & Permissions Page`, `7. Permissions Page`) [14].
- Audit Log Table with search and date filter (`11. Audit Logs Page`) [14].

### Dependencies
```text
Depends on:
- Phase 2 (Master Data & Context)
```

### Database Impact
- **New Table**: `roles` (`id`, `organization_id`, `name`, `description`, `is_system`).
- **New Table**: `permissions` (`id`, `role_id`, `module_code`, `can_view`, `can_create`, `can_edit`, `can_delete`, `can_export`).
- **New Table**: `audit_logs` (`id`, `user_id`, `module`, `action`, `ip_address`, `payload_before`, `payload_after`, `created_at`).
- **Modified Table**: `users` (added `role_id`, `project_ids`).

### API Impact
```text
New APIs:
- GET /api/v1/users
- POST /api/v1/users
- PUT /api/v1/users/:id
- GET /api/v1/roles
- POST /api/v1/roles
- PUT /api/v1/roles/:id/permissions
- GET /api/v1/audit-logs
```

### Authorization / Roles
- Super Admin has full system access [1, 14].
- Admin can manage users, roles, and permissions [1, 14].
- Other roles have immutable access based on permission matrix [1, 14].

### Business Rules
- Deactivated users cannot log in or call APIs [1, 14].
- System roles (Super Admin) cannot be deleted [14].

### Edge Cases
- User permission revoked while actively logged in -> Middleware rejects subsequent protected requests with HTTP 403 [1].

### Testing Requirements
- Unit test for RBAC permission middleware bitwise or boolean checks.
- Integration test ensuring audit log entry created on user update.

### Completion Criteria
```text
Phase is complete when:
- Admin can create a custom role and toggle individual module permissions.
- Revoking 'export' permission removes export buttons from UI and blocks export API routes.
- Audit log records all configuration and data mutation events.
```

---

## 12. Phase 4 — Lead Acquisition & Multi-Channel Sync

### Objective
Capture leads from Meta Ads, Google Ads, manual inputs, and CSV file imports while detecting duplicates and validating contact info [19].

### Business Purpose
Automate lead ingestion from marketing channels into a centralized pipeline, preventing lost leads and eliminating duplicate outreach [19].

### Features Included
- Lead Sources Overview & Sync Cards (Meta Ads, Google Ads, Manual, CSV) [19].
- Meta & Google Ads Sync & Preview Modals [19].
- Manual Lead Creation Form with mandatory field validation [19].
- CSV Drag-and-Drop Import Wizard with field mapping & error report download [19].
- Phone + Email Duplicate Detection Modal with confidence matching scores (95%, 90%, 80%) [19].

### Backend Work
- Meta Graph API & Google Ads API webhook receivers and manual sync service.
- CSV parsing worker with chunked processing (max file size 5MB) [19].
- Weighted Duplicate Match Algorithm:
  - Phone Exact Match = 95% confidence [19].
  - Phone Match + Different Name = 90% confidence [19].
  - Email Match + Partial Phone = 80% confidence [19].
- Duplicate resolution logic (Create Anyway vs Merge with Existing) [19].

### Frontend Work
- Lead Sources Dashboard (`1. Lead Sources Overview`) [19].
- Ad Integration Sync Modals (`2. Meta Leads`, `3. Google Leads`) [19].
- Manual Lead Form (`4. Manual Lead Creation`) [19].
- CSV Import Modal (`5. Import Leads CSV`, `11`, `12`) [19].
- Duplicate Match Modal (`6. Duplicate Detection`) [19].

### Dependencies
```text
Depends on:
- Phase 3 (Users & RBAC)
```

### Database Impact
- **New Table**: `leads` (`id`, `lead_code`, `organization_id`, `project_id`, `full_name`, `phone`, `email`, `source_id`, `owner_id`, `status_id`, `score`, `budget_range`, `preferred_location`, `created_at`).
- **New Table**: `lead_import_batches` (`id`, `file_name`, `total_rows`, `imported_rows`, `skipped_rows`, `created_by`).

### API Impact
```text
New APIs:
- POST /api/v1/leads/sync/meta
- POST /api/v1/leads/sync/google
- POST /api/v1/leads/manual
- POST /api/v1/leads/import-csv
- POST /api/v1/leads/check-duplicate
- POST /api/v1/leads/merge
```

### Authorization / Roles
- Telecallers, Site Visit Execs, Managers, Admins can create manual leads [19].
- Admins/Managers can trigger ad sync and import CSV files [19].

### Business Rules
- Phone number is mandatory for all leads [19].
- Imported rows missing mandatory fields are skipped and listed in error download CSV [19].

### Edge Cases
- CSV contains 10,000 rows -> Process asynchronously via background job, updating import batch progress bar [19].
- Meta Ads webhook sends duplicate lead ID -> Idempotently update or ignore existing payload [19].

### Testing Requirements
- Unit tests for phone number regex formatting and duplicate scoring weights.
- Integration test for CSV import parsing with malformed rows.

### Completion Criteria
```text
Phase is complete when:
- Manual leads can be saved with immediate duplicate warning dialog.
- CSV import successfully ingests valid rows and generates download error log for invalid ones.
- Duplicate detection algorithm scores matches accurately.
```

---

## 13. Phase 5 — Lead Qualification & Lifecycle Management

### Objective
Provide comprehensive lead listing, multi-param filtering, detail slide-over view, manual assignment/reassignment, and stage lifecycle tracking [20].

### Business Purpose
Enable sales managers and executives to qualify, assign, track, and convert leads through structured sales pipeline stages [20].

### Features Included
- Lead List Table View with status badges, score, and quick action bar [20].
- Multi-parameter Search & Filter Modal (Source, Status, Owner, City, Date, Score, Tags) [20].
- Lead Details Overview Slide-Over (Lead Score badge, Contact details, Qualification tabs, Activity timeline) [20].
- Assign / Reassign Lead Modals with reason logging [20].
- Bulk Actions Toolbar (Assign, Change Status, Add Tag, Export, Delete) [20].
- Lead Status Lifecycle Engine (New -> Contacted -> Interested -> Site Visit Scheduled -> Site Visit Completed -> Converted / Lost) [20].

### Backend Work
- Lead listing endpoint with dynamic multi-clause filtering, pagination, and sorting [20].
- Lead assignment service with ownership history tracking [20].
- Status transition state machine enforcing valid state moves [20].
- Bulk updates transaction executor [20].

### Frontend Work
- Lead List Page (`1. Lead List - Default View`) [20].
- Search & Filter Drawer (`2. Search & Filters`) [20].
- Lead Detail Overview (`3. Lead Details - Overview`) [20].
- Assign / Reassign Modals (`4`, `5`) [20].
- Status Lifecycle Component (`6. Lead Status Lifecycle`) [20].
- Bulk Actions Floating Bar (`7. Bulk Actions`) [20].

### Dependencies
```text
Depends on:
- Phase 4 (Lead Acquisition)
```

### Database Impact
- **New Table**: `lead_assignments_history` (`id`, `lead_id`, `assigned_from_id`, `assigned_to_id`, `reason`, `assigned_by`, `created_at`).
- **New Table**: `lead_status_history` (`id`, `lead_id`, `old_status_id`, `new_status_id`, `changed_by`, `created_at`).
- **New Table**: `lead_tags` (`id`, `lead_id`, `tag_name`).

### API Impact
```text
New APIs:
- GET /api/v1/leads
- GET /api/v1/leads/:id
- PUT /api/v1/leads/:id
- POST /api/v1/leads/:id/assign
- POST /api/v1/leads/:id/status
- POST /api/v1/leads/bulk-action
```

### Authorization / Roles
- Non-admin users can edit only leads assigned to them unless granted team view permission [1, 20].
- Only Managers/Admins can reassign leads or perform bulk deletion [20].

### Business Rules
- Converted leads cannot be edited in key fields [20].
- Status changes are immutable and saved in `lead_status_history` with timestamp and user ID [20].

### Edge Cases
- Lead assigned to an inactive employee -> Auto-flag for reassignment in Manager view [20].

### Testing Requirements
- Unit tests for lead filter SQL query generator.
- E2E test for changing lead status from New to Contacted and verifying timeline update.

### Completion Criteria
```text
Phase is complete when:
- Lead list supports complex filtering and instant pagination.
- Lead detail slide-over displays complete assignment and status history.
- Bulk assignment updates owner field across selected items seamlessly.
```

---

## 14. Phase 6 — Telecalling Operations & Calling Queue

### Objective
Implement telecaller work environment, including dynamic call queues, active call control panel, outcome dispositions, and follow-up task creation [21].

### Business Purpose
Maximize telecaller productivity, standardize call logging, enforce follow-up SLAs, and increase lead-to-site-visit conversion rates [21].

### Features Included
- Calling Queue Table (Assigned, Pending, Connected, Follow-ups) [21].
- Active Call Screen with timer, mute/hold toggles, and quick note pad [21].
- Call Outcome Dispositions (Interested, Callback Later, Busy, No Answer, Switched Off, Wrong Number, DND, Already Purchased) [21].
- Follow-up Task Scheduler Modal [21].
- Multiple Call Attempt History Tracker [21].
- Call Analytics Summary Header [21].

### Backend Work
- Dynamic Call Queue algorithm (sorting leads by scheduled follow-up time, lead score, and pending attempt status) [21].
- Call attempt logger service [21].
- Follow-up creation service triggering reminder alerts [21].

### Frontend Work
- Calling Queue Page (`1. Calling Queue`) [21].
- Active Call Modal Screen (`2. Call Screen - Active Call`) [21].
- Call Dispositions Component (`3. Call Outcomes`) [21].
- Follow-up Form Modal (`4. Create Follow-up`) [21].
- Call Attempt History Timeline (`6. Multiple Call Attempts`) [21].
- Call Analytics Component (`8. Call Analytics`) [21].

### Dependencies
```text
Depends on:
- Phase 5 (Lead Management)
```

### Database Impact
- **New Table**: `call_logs` (`id`, `lead_id`, `caller_id`, `call_duration_seconds`, `disposition`, `notes`, `created_at`).
- **New Table**: `follow_ups` (`id`, `lead_id`, `assigned_to_id`, `follow_up_date`, `type`, `reason`, `status`, `reminder_sent`).

### API Impact
```text
New APIs:
- GET /api/v1/telecalling/queue
- POST /api/v1/telecalling/calls/start
- POST /api/v1/telecalling/calls/end
- POST /api/v1/telecalling/follow-ups
- GET /api/v1/telecalling/analytics
```

### Authorization / Roles
- Telecallers view and process only leads in their assigned queue [21].
- Managers can view team call analytics and redistribute queues [21].

### Business Rules
- Ending an active call requires selecting a valid disposition outcome [21].
- Selecting 'Callback Later' or 'Interested' mandates setting a follow-up date and time [21].

### Edge Cases
- Network failure during active call -> Auto-save draft notes and prompt caller to submit disposition on reconnect [21].

### Testing Requirements
- Unit test for call queue ordering SQL view.
- E2E test for starting a call, setting timer, selecting 'Callback Later', and confirming follow-up task created.

### Completion Criteria
```text
Phase is complete when:
- Telecaller can cycle through calling queue sequentially without manually searching leads.
- Active call timer operates accurately.
- Dispositions save call logs and automatically update lead status/follow-ups.
```

---

## 15. Phase 7 — Site Visit Scheduling & Execution

### Objective
Provide scheduling, calendar views, executive dispatch, site visit outcome logging, and rating mechanisms for plot site visits [22].

### Business Purpose
Convert interested leads into plot bookings by facilitating seamless on-site property tours and capturing customer feedback [22].

### Features Included
- Site Visit Calendar (Month view) & List View [22].
- Schedule, Reschedule, and Cancel Site Visit Modals [22].
- Executive Assignment & Meeting Point capture [22].
- Visit Outcome Logging (Interested, Need More Time, Price Issue, Location Issue, Loan Issue, Already Purchased, Wrong Requirement) [22].
- Customer Interest Level Rating (1 to 5 Stars) [22].
- No-Show Management & Follow-up trigger [22].

### Backend Work
- Site Visit scheduling engine with conflict check for executive availability [22].
- Status state machine (Scheduled -> In Progress -> Completed / Cancelled / No Show) [22].
- Automated lead score boost (+20 points on visit completion) [20, 22].

### Frontend Work
- Calendar View Component (`1. Site Visit Calendar - Month View`) [22].
- Schedule / Reschedule / Cancel Modals (`4`, `5`, `6`) [22].
- Visit Outcome & Star Rating Form (`7. Visit Outcome - After Completion`) [22].
- Today's Visits Executive View (`10. Today's Visits`) [22].
- Site Visit Summary Analytics (`12. Visit Analytics`) [22].

### Dependencies
```text
Depends on:
- Phase 5 (Lead Management)
```

### Database Impact
- **New Table**: `site_visits` (`id`, `lead_id`, `project_id`, `executive_id`, `visit_date`, `duration_mins`, `meeting_point`, `customer_preference`, `status`, `outcome`, `interest_rating`, `remarks`, `created_at`).

### API Impact
```text
New APIs:
- GET /api/v1/site-visits
- POST /api/v1/site-visits
- PUT /api/v1/site-visits/:id/reschedule
- PUT /api/v1/site-visits/:id/outcome
- POST /api/v1/site-visits/:id/no-show
```

### Authorization / Roles
- Site Visit Executives can view and update site visits assigned to them [22].
- Managers and Admins can assign or reschedule visits for any team member [22].

### Business Rules
- Visits can only be scheduled for active, valid leads [22].
- No future visit date can be scheduled beyond 90 days from current date (configurable) [22].

### Edge Cases
- Executive marks visit 'In Progress' -> Enable quick access to plot inventory selection map [22, 24].

### Testing Requirements
- Unit test preventing site visit creation past the 90-day threshold.
- Integration test for site visit outcome submission updating lead interest rating.

### Completion Criteria
```text
Phase is complete when:
- Calendar view displays color-coded site visits accurately.
- Site visit completion captures 1-5 star rating and feedback remarks.
- Lead status auto-updates to 'Site Visit Completed'.
```

---

## 16. Phase 8 — Plot Inventory Management & Interactive Layout Map

### Objective
Construct plot database, plot status lifecycle manager, and interactive color-coded layout grid visualizer with hold/block functionality [23, 24].

### Business Purpose
Provide real-time visibility into plot availability, pricing, dimensions, and status, eliminating double-selling risks [23, 24].

### Features Included
- Plot Inventory Table View with multi-filters (Block, Plot Type, Status, Rate) [23].
- Interactive Map / Grid Layout Visualizer with color legend (Available [Green], Booked [Purple], Hold [Orange], Blocked [Red], Sold [Dark Green], Under Construction [Grey]) [24].
- Plot Details Slide-Over / Modal [23, 24].
- Block / Hold Plot Modal with reason capture and timer [23, 24].
- Plot History Timeline [23].
- Bulk Plot Status Update Modal (up to 500 plots) [23].

### Backend Work
- Plot Inventory CRUD & search service [23].
- Distributed lock manager for plot status mutation (Redis / DB transaction locks) [23, 24].
- Plot hold auto-expiry background worker (polling Redis TTL or DB timestamps to release expired holds) [23, 24].
- Bulk update transaction executor [23].

### Frontend Work
- Plot Table View (`3. Wireframes - Key Screens`) [23].
- Interactive Layout Grid Visualizer (`3.5 Plot Map / Layout View`) [23, 24].
- Plot Details Slide-Over (`3.2 Plot Details - View`, `4.2`) [23, 24].
- Block / Hold Modal (`3.4 Block / Hold Plot Modal`) [23].
- Bulk Update Status Modal (`3.7 Bulk Update Status`) [23].

### Dependencies
```text
Depends on:
- Phase 2 (Master Data)
```

### Database Impact
- **New Table**: `plots` (`id`, `project_id`, `block_name`, `plot_number`, `size_sqyd`, `facing`, `plot_type`, `rate_per_sqyd`, `total_price`, `status`, `created_at`).
- **New Table**: `plot_status_history` (`id`, `plot_id`, `old_status`, `new_status`, `reason`, `hold_from`, `hold_to`, `changed_by`, `created_at`).

### API Impact
```text
New APIs:
- GET /api/v1/plots
- GET /api/v1/plots/:id
- POST /api/v1/plots
- PUT /api/v1/plots/:id/hold
- PUT /api/v1/plots/:id/release
- POST /api/v1/plots/bulk-status
```

### Authorization / Roles
- Telecallers and Accounts have Read-Only view of plot inventory [23, 24].
- Site Visit Execs can view plot details and request temporary holding [23, 24].
- Managers and Admins can block, release, edit, or perform bulk plot updates [23, 24].

### Business Rules
- A plot can be in only one active status at any given time [23].
- Blocked or Held plots cannot be selected for new bookings [23, 24].

### Edge Cases
- Executive attempts to block a plot simultaneously being booked by another user -> System returns concurrency error with lock details [24].

### Testing Requirements
- Concurrency unit test executing 50 parallel hold requests for the same plot ID (ensure exactly 1 succeeds).
- Background job test verifying expired plot holds revert to 'Available' status automatically.

### Completion Criteria
```text
Phase is complete when:
- Plot layout grid renders color-coded statuses accurately.
- Placing a plot on Hold updates real-time map state and starts expiry timer.
- Bulk update processes status modifications safely with audit history logs.
```

---

## 17. Phase 9 — Booking Management Workflow

### Objective
Build end-to-end booking flow including plot availability re-checking, pricing calculation, non-refundable hold enforcement, and receipt generation [2].

### Business Purpose
Secure plot sales transactions, capture customer purchase commitments, and generate official booking contracts and payment receipts [2].

### Features Included
- Multi-Step Booking Wizard (Select Customer -> Select Plot -> Booking Details -> Payment Details -> Booking Confirmation) [2].
- Pre-booking Availability Re-Check Engine with conflict screen [24].
- Booking List & Detail View with status badges [2].
- Booking Status Lifecycle (Created -> Payment Pending -> Partially Paid -> Confirmed -> Cancelled / Expired) [2].
- Booking Summary & Printable Receipt Generator [2].
- Booking Cancellation & Plot Release Modal [2].

### Backend Work
- Booking creation transactional service:
  1. Acquire lock on Plot ID.
  2. Re-verify plot status is 'Available' or 'Held by user'.
  3. Create Booking record.
  4. Mutate Plot status to 'Booked'.
  5. Log initial payment entry.
  6. Release lock.
- Automated hold expiry job releasing expired unconfirmed bookings [2].
- PDF Booking Receipt generation service.

### Frontend Work
- Booking List View (`4.1 My Bookings`) [2].
- Customer Selection Screen (`4.2 Select Customer`) [2].
- Plot Selection & Live Re-check Modals (`4.3`, `4.4 Availability Re-check`) [2, 24].
- Booking & Payment Form (`4.4 Booking Details`, `4.5 Payment Details`) [2].
- Booking Confirmation & Receipt Modal (`4.6 Booking Confirmation`) [2].

### Dependencies
```text
Depends on:
- Phase 5 (Lead Management)
- Phase 8 (Plot Inventory)
```

### Database Impact
- **New Table**: `bookings` (`id`, `booking_code`, `project_id`, `customer_id`, `plot_id`, `booking_date`, `total_amount`, `discount_amount`, `net_amount`, `booking_amount_paid`, `status`, `hold_expires_at`, `created_by`, `created_at`).

### API Impact
```text
New APIs:
- GET /api/v1/bookings
- POST /api/v1/bookings
- GET /api/v1/bookings/:id
- POST /api/v1/bookings/:id/cancel
- GET /api/v1/bookings/:id/receipt
```

### Authorization / Roles
- Site Visit Execs and Telecallers can initiate bookings for assigned leads [2].
- Managers and Admins can modify, approve, or cancel bookings [2].

### Business Rules
- A plot can have only one active booking [2].
- Booking holds plot for a configurable window (e.g., 7 days); if minimum payment is not received, hold auto-expires and plot reverts to 'Available' [2].

### Edge Cases
- Payment gateway drops connection during booking submission -> Retain booking in 'Payment Pending' state for 15 mins before releasing plot [2].

### Testing Requirements
- Integration test for end-to-end booking flow verifying DB transactional integrity across `bookings` and `plots` tables.
- PDF generation unit test confirming layout formatting and receipt number sequence.

### Completion Criteria
```text
Phase is complete when:
- Complete booking wizard executes smoothly from customer selection to receipt rendering.
- Plot status switches to 'Booked' immediately upon submission.
- Conflict modal displays if plot status changes prior to final step.
```

---

## 18. Phase 10 — Customer Management & 360° Profile

### Objective
Create customer directory, status transition manager, and 360° profile view consolidating all interactions, bookings, payments, and documents [3].

### Business Purpose
Provide single source of truth for customer history, aiding relationship management, post-sales communication, and registry compliance [3].

### Features Included
- Customer List Table View with status badges and quick search [3].
- Add / Edit Customer Slide-Over [3].
- 360° Customer Profile Dashboard (Basic Details, Status Lifecycle, Total Bookings, Payments, Outstanding Dues) [3].
- Unified Activity Timeline (Leads, Site Visits, Bookings, Payments, Uploaded Documents, Notes) [3].
- Linked Modules Summary Cards [3].

### Backend Work
- Customer record creation service (auto-triggered on lead conversion or manual creation) [3, 20].
- Customer 360° aggregator API collecting records across 6 sub-systems [3].
- Customer status lifecycle manager (New -> Active -> Engaged -> Converted -> Inactive / Blacklisted) [3].

### Frontend Work
- Customer List View (`4.1 Customer List`) [3].
- Customer Form (`4.2 Add/Edit Customer`) [3].
- 360° Profile Dashboard (`3. Key Customer Info`, `4.3 Customer Profile - Overview`) [3].
- Communication & Activity History Tabs (`4.4 Communication History`) [3].
- Linked Modules Panel (`4.5 Linked Modules Summary`) [3].

### Dependencies
```text
Depends on:
- Phase 9 (Booking Management)
```

### Database Impact
- **New Table**: `customers` (`id`, `customer_code`, `organization_id`, `lead_id`, `full_name`, `phone`, `email`, `address`, `status`, `created_at`).
- **New Table**: `customer_notes` (`id`, `customer_id`, `author_id`, `note_text`, `created_at`).

### API Impact
```text
New APIs:
- GET /api/v1/customers
- POST /api/v1/customers
- GET /api/v1/customers/:id/360
- POST /api/v1/customers/:id/notes
```

### Authorization / Roles
- Site Visit Execs and Telecallers view customer profiles assigned to them [3].
- Managers and Admins can edit details or change customer status [3].

### Business Rules
- Customer phone and email must be unique across the organization [3].
- Deleting customer records is forbidden; inactive profiles must be set to 'Inactive' or 'Blacklisted' with logged reason [3].

### Edge Cases
- Attempting to create duplicate customer profile -> Prompt with link to view existing 360° profile [3].

### Testing Requirements
- Aggregator service integration test verifying accurate count of linked bookings and total outstanding dues.
- Frontend test for profile tabs rendering correct sub-module lists.

### Completion Criteria
```text
Phase is complete when:
- Converting a lead automatically populates a comprehensive customer profile.
- 360° profile aggregates timeline events chronologically across all sub-modules.
```

---

## 19. Phase 11 — Payment Management, Dues & Financial Ledger

### Objective
Implement multi-mode payment entry, multi-due selection, payment receipts, customer ledger accounting, and role-based refund workflows [4].

### Business Purpose
Maintain accurate financial records, track outstanding collections, streamline receipting, and ensure complete audit compliance [4].

### Features Included
- Payment List & Summary Cards (Total Dues, Total Paid, Outstanding Balance) [4].
- Add Payment Modal with multi-due selection checkboxes (Booking Amount, Maintenance, Legal Fees) [4].
- Payment Modes interface (UPI, Card, Net Banking, Cash, Cheque) [4].
- Customer Payment Ledger Table (Opening Balance, Debits, Credits, Running Balance) [4].
- Refund & Adjustment Approval Workflow Modal [4].
- Printable Payment Receipt Generator [4].

### Backend Work
- Payment processing service with transactional double-entry ledger updates [4].
- Outstanding dues calculation engine [4].
- Refund request and approval state machine [4].
- Immutable transaction enforcement (edits disabled; adjustments require explicit credit/debit entries) [4].

### Frontend Work
- Payments List View (`4.1 Payment List`) [4].
- Add Payment Modal (`4.2 Add Payment`, `4.3 Payment Details`, `4.4 Choose Payment Mode`) [4].
- Receipt Generator Modal (`4.6 Receipt Generated`) [4].
- Customer Ledger View (`7. Payment Ledger`) [4].
- Refunds & Adjustments Modal (`6. Refunds & Adjustments`) [4].

### Dependencies
```text
Depends on:
- Phase 9 (Booking Management)
- Phase 10 (Customer Management)
```

### Database Impact
- **New Table**: `payments` (`id`, `receipt_code`, `booking_id`, `customer_id`, `amount_paid`, `payment_mode`, `payment_date`, `txn_reference`, `status`, `received_by`, `created_at`).
- **New Table**: `payment_due_allocations` (`id`, `payment_id`, `due_type`, `amount_allocated`).
- **New Table**: `refunds_adjustments` (`id`, `payment_id`, `type`, `amount`, `reason`, `status`, `approved_by`, `created_at`).

### API Impact
```text
New APIs:
- GET /api/v1/payments
- POST /api/v1/payments
- GET /api/v1/payments/ledger/:customer_id
- POST /api/v1/payments/refunds
- PUT /api/v1/payments/refunds/:id/approve
```

### Authorization / Roles
- Accounts staff and Managers can log payments and generate receipts [4].
- Only Admins and Finance Heads can approve refund or adjustment requests [4].

### Business Rules
- Excess payments are credited to the customer's advance ledger account balance [4].
- Deleting or editing recorded payments is strictly prohibited [4].

### Edge Cases
- Cheque payment submitted -> Payment set to 'Pending Realization' until Accounts updates status to 'Cleared' [4].

### Testing Requirements
- Financial math unit test for running ledger balances and due allocations.
- Security test confirming non-admin users cannot call refund approval routes.

### Completion Criteria
```text
Phase is complete when:
- Multi-due selection correctly splits and attributes payments.
- Customer ledger accurately reflects debits, credits, and outstanding balances.
- Receipts render clean PDF previews with unique reference codes.
```

---

## 20. Phase 12 — Documents & eKYC Verification

### Objective
Provide secure document storage, categorization, expiration monitoring, and third-party API integration for Aadhaar, PAN, and Face eKYC verification [5].

### Business Purpose
Verify customer legal identity, satisfy statutory anti-money laundering compliance, and prevent fraudulent property bookings [5].

### Features Included
- Document Directory List with category filters (ID Proof, Address Proof, Financial, eKYC) [5].
- Upload Document Modal supporting PDF, JPG, PNG (max 10MB) [5].
- Document Details & Preview Modal [5].
- Automated eKYC Verification Panel (Aadhaar UIDAI, PAN NSDL, Address, Face Match score) [5].
- Expiry Alerts Summary & Expiry Calendar View [5].
- Pending Verification Review Queue [5].

### Backend Work
- Cloud Storage integration (AWS S3 / GCP Bucket) with AES-256 encryption.
- Third-party eKYC provider API connectors (Aadhaar OTP/Biometric API, NSDL PAN verification API) [5].
- Face Match confidence scoring service [5].
- Document expiry notification background job [5].

### Frontend Work
- Documents List View (`4.1 Documents List`) [5].
- Upload Modal (`4.2 Upload Document Modal`) [5].
- eKYC Verification Panel (`4.4 eKYC Verification`) [5].
- Expiry Calendar View (`5. Expiry Calendar View`) [5].
- Pending Verification Queue Table (`6. Pending Verification Queue`) [5].

### Dependencies
```text
Depends on:
- Phase 10 (Customer Management)
```

### Database Impact
- **New Table**: `customer_documents` (`id`, `customer_id`, `category`, `document_name`, `file_url`, `file_size_bytes`, `expiry_date`, `status`, `uploaded_by`, `created_at`).
- **New Table**: `ekyc_verifications` (`id`, `customer_id`, `provider`, `id_number`, `verification_status`, `response_payload`, `verified_at`).

### API Impact
```text
New APIs:
- GET /api/v1/documents
- POST /api/v1/documents/upload
- POST /api/v1/documents/verify-ekyc
- GET /api/v1/documents/expiry-alerts
```

### Authorization / Roles
- Site Visit Execs and Telecallers can upload customer documents [5].
- Managers and Admins can approve or reject uploaded documents and run eKYC checks [5].

### Business Rules
- eKYC verification must be completed prior to final registry execution [5, 7].
- Expired documents automatically flag alerts 30 days prior to expiration [5].

### Edge Cases
- eKYC provider API service outage -> Queue request for retry and display graceful status banner [5].

### Testing Requirements
- S3 upload unit test verifying secure pre-signed URL generation.
- Mock API integration test for Aadhaar and PAN verification response handling.

### Completion Criteria
```text
Phase is complete when:
- Files upload securely with document type and expiry metadata.
- Third-party eKYC mock verification returns verified status badge.
- Expiry calendar highlights upcoming document expirations.
```

---

## 21. Phase 13 — Registry Management & Sale Deed Process

### Objective
Track plot registry workflows, record sub-registrar details, calculate legal and stamp duty fees, and manage mandatory document submissions [7].

### Business Purpose
Manage post-booking legal ownership transfers, ensuring compliance with local government property registration requirements [7].

### Features Included
- Registry List Table with status filters (Pending, In Process, Completed, Cancelled) [7].
- Add Registry & Plot Selection Modal [7].
- Registry Info & Sub-Registrar Details Form [7].
- Charges Calculator Breakdown (Stamp Duty, Registration Charges, Legal Fees, TDS, Total Consideration) [7].
- Mandatory Legal Documents Verification Checklist [7].
- Registry Timeline History [7].

### Backend Work
- Registry process tracking service [7].
- Automated tax and stamp duty fee calculation engine [7].
- Document checklist validation guard [7].

### Frontend Work
- Registry List Page (`3.1 Registry List Page`) [7].
- Add Registry Wizard (`4. Add Registry Page`, `5. Registry Info Page`) [7].
- Charges Breakdown Page (`6. Charges Page`) [7].
- Documents Checklist Page (`7. Documents Page`) [7].
- Registry Details View (`9. Registry Details View`) [7].

### Dependencies
```text
Depends on:
- Phase 9 (Booking Management)
- Phase 11 (Payment Management)
- Phase 12 (Documents & eKYC)
```

### Database Impact
- **New Table**: `registries` (`id`, `registry_code`, `plot_id`, `customer_id`, `registry_date`, `sub_registrar_office`, `agreement_no`, `consideration_amount`, `stamp_duty`, `registration_charges`, `legal_fees`, `tds_amount`, `status`, `created_at`).

### API Impact
```text
New APIs:
- GET /api/v1/registries
- POST /api/v1/registries
- PUT /api/v1/registries/:id/status
- GET /api/v1/registries/:id/charges
```

### Authorization / Roles
- Only Admins and Legal Officers can create or update registry status [7].
- Managers and Accounts staff have view permissions [7].

### Business Rules
- Registry can be initiated only for plots with confirmed bookings and zero pending payment dues [4, 7].

### Edge Cases
- Registry cancelled -> Revert plot status to 'Booked' or prompt for refund handling [2, 4, 7].

### Testing Requirements
- Unit test for stamp duty calculation rules.
- Integration test checking that unverified eKYC blocks registry completion.

### Completion Criteria
```text
Phase is complete when:
- Registry form calculates complete fee breakdown accurately.
- Legal documents checklist verifies all uploads before allowing 'Completed' status transition.
```

---

## 22. Phase 14 — Multi-Channel Communication Engine & Auto-Triggers

### Objective
Construct outbound messaging engine for WhatsApp, SMS, and Email, supporting template management, variable substitution, and auto-trigger rules [10].

### Business Purpose
Automate customer communication across all touchpoints, improving site visit show-up rates, payment collection promptness, and document compliance [10].

### Features Included
- Communication Dashboard (Sent, Delivered, Read, Bounced statistics across WhatsApp, SMS, Email) [10].
- Direct Message Senders (WhatsApp, SMS, Email) [10].
- Templates Builder with dynamic placeholders (`{customer_name}`, `{plot_no}`, `{due_amount}`) [10].
- Automated Trigger Rules Configuration (e.g., Payment Due 3 days before -> Send SMS) [10].
- Communication Logs Viewer [10].

### Backend Work
- Multi-provider gateway connectors (WhatsApp Business API, MSG91 SMS, AWS SES SMTP Email) [10].
- Template rendering engine with variable injection [10].
- Event-driven communication worker processing auto-trigger rules [10].
- Webhook endpoints receiving delivery and read receipts [10].

### Frontend Work
- Communication Dashboard (`3. Communication Dashboard`) [10].
- Message Composers (`4. WhatsApp Send`, `5. SMS Send`, `6. Email Send`) [10].
- Template Manager (`7. Templates Management Page`) [10].
- Auto Trigger Rules Configuration (`11. Auto Trigger Rules Page`) [10].
- Delivery Logs Table (`8. Communication Logs Page`, `9. Delivery Status Details`) [10].

### Dependencies
```text
Depends on:
- Phase 2 (Master Data & Settings)
- Phase 5 (Lead Management)
- Phase 9 (Booking Management)
```

### Database Impact
- **New Table**: `communication_templates` (`id`, `channel`, `template_name`, `content_body`, `variables`, `approval_status`, `created_at`).
- **New Table**: `auto_trigger_rules` (`id`, `event_type`, `days_offset`, `channel`, `template_id`, `is_active`).
- **New Table**: `communication_logs` (`id`, `recipient_phone_email`, `channel`, `template_id`, `message_body`, `status`, `vendor_msg_id`, `sent_at`).

### API Impact
```text
New APIs:
- POST /api/v1/communication/send
- GET /api/v1/communication/templates
- POST /api/v1/communication/templates
- GET /api/v1/communication/triggers
- POST /api/v1/communication/triggers
```

### Authorization / Roles
- Admins and Managers can configure templates and trigger rules [10].
- Telecallers and Executives can trigger manual templated messages to assigned leads [10].

### Business Rules
- WhatsApp templates must be approved by Meta before deployment [10].
- Messages are dispatched strictly within allowed operational hours (e.g., 9 AM - 8 PM) [10].

### Edge Cases
- Recipient opted out of marketing communications -> Skip dispatch and log 'Opted Out' status [10].

### Testing Requirements
- Unit test for variable template parser replacing placeholders correctly.
- Mock webhook integration test processing 'Delivered' and 'Read' status callbacks.

### Completion Criteria
```text
Phase is complete when:
- Direct messaging modal sends templated WhatsApp, SMS, and Email messages.
- Trigger rules execute automatically upon system events (e.g., site visit scheduled).
```

---

## 23. Phase 15 — Employee Management & Mini-HRMS

### Objective
Provide employee directory, attendance tracking, leave request approval workflow, performance reviews, and HR document management [8, 15].

### Business Purpose
Manage internal workforce records, monitor staff attendance, streamline leave management, and track sales team performance [8, 15].

### Features Included
- Employee List Directory [8, 15].
- Add / Edit Employee Profile Wizard (Personal, Job, Role, Compensation info) [8, 15].
- Daily Attendance Check-In / Check-Out Log [15].
- Leave Request & Approval Page (Casual, Sick, Paid Leave) [15].
- Performance Review Log Page [15].
- Employee Document Repository (Offer Letter, Salary Slips, PAN, Aadhaar) [15].

### Backend Work
- HRMS Employee Management CRUD service [8, 15].
- Daily attendance logger with geolocation / IP check [15].
- Leave approval state machine (Pending -> Approved / Rejected) updating leave balances [15].
- Employee document encryption and storage [15].

### Frontend Work
- Employee Directory (`3. Employee List Page`) [8, 15].
- Employee Profile Editor (`4. Add/Edit Employee`, `7. Employee Profile View`) [8, 15].
- Attendance Page (`6. Attendance Page`) [15].
- Leave Management Component (`7. Leave Management Page`) [15].
- Performance Review View (`8. Performance Review Page`) [15].

### Dependencies
```text
Depends on:
- Phase 3 (User Administration)
```

### Database Impact
- **New Table**: `employees` (`id`, `user_id`, `employee_code`, `department`, `designation`, `reporting_manager_id`, `date_of_joining`, `salary`, `status`).
- **New Table**: `employee_attendance` (`id`, `employee_id`, `work_date`, `check_in_time`, `check_out_time`, `total_hours`, `status`).
- **New Table**: `leave_requests` (`id`, `employee_id`, `leave_type`, `from_date`, `to_date`, `total_days`, `reason`, `status`, `approved_by`).

### API Impact
```text
New APIs:
- GET /api/v1/employees
- POST /api/v1/employees
- POST /api/v1/employees/attendance/check-in
- POST /api/v1/employees/attendance/check-out
- GET /api/v1/employees/leaves
- POST /api/v1/employees/leaves
- PUT /api/v1/employees/leaves/:id/approve
```

### Authorization / Roles
- Employees can view personal profile, log attendance, and apply for leaves [8, 15].
- Managers and HR Admins can approve leaves, submit reviews, and manage profiles [8, 15].

### Business Rules
- Leave requests require reporting manager approval [15].
- Deactivated employee user accounts are blocked from system login [1, 15].

### Edge Cases
- Employee submits overlapping leave request -> Validation error prevents duplicate application [15].

### Testing Requirements
- Unit test for working hour calculation between check-in and check-out timestamps.
- Integration test for leave balance deduction upon approval.

### Completion Criteria
```text
Phase is complete when:
- Employee check-in/check-out logs timestamp accurately.
- Leave approval workflow updates status and notifies employee.
```

---

## 24. Phase 16 — Expenses Tracker & Approval Workflow

### Objective
Track business operational expenses, receipt document attachments, manager review and approval workflows, and reimbursement processing [9, 16].

### Business Purpose
Provide strict financial control over company expenditures, travel claims, marketing expenses, and site visit reimbursements [9, 16].

### Features Included
- Expenses List Table with status indicators (Pending, Approved, Rejected, Paid) [9, 16].
- Add Expense Page with category selection, bill receipt upload, and draft saving [9, 16].
- Expense Details & Receipt Viewer Page [9, 16].
- Manager Approval / Rejection Workflow Modal [9, 16].
- Payment & Reimbursement Tracking Screen [9, 16].
- Expense Category Manager [9, 16].

### Backend Work
- Expense tracking CRUD service [9, 16].
- Receipt document upload integration [9, 16].
- Expense approval state machine [9, 16].
- Reimbursement disbursement status logger [9, 16].

### Frontend Work
- Expense List Screen (`3. Expenses List Page`) [9, 16].
- Add Expense Form (`4. Add Expense Page`) [9, 16].
- Expense Details Component (`5. Expense Details Page`) [9, 16].
- Manager Approval Panel (`6. Approval Workflow`) [9, 16].
- Reimbursements Screen (`7. Payment & Reimbursement Page`) [9, 16].

### Dependencies
```text
Depends on:
- Phase 3 (User Administration)
- Phase 15 (Employee Management)
```

### Database Impact
- **New Table**: `expenses` (`id`, `expense_code`, `employee_id`, `category_id`, `amount`, `expense_date`, `description`, `receipt_url`, `status`, `approved_by`, `paid_status`, `created_at`).

### API Impact
```text
New APIs:
- GET /api/v1/expenses
- POST /api/v1/expenses
- PUT /api/v1/expenses/:id/approve
- PUT /api/v1/expenses/:id/reject
- POST /api/v1/expenses/:id/reimburse
```

### Authorization / Roles
- Employees can submit and view personal expense claims [9, 16].
- Managers can review, approve, or reject team expense claims [9, 16].
- Accounts staff can process reimbursement disbursements [9, 16].

### Business Rules
- Expenses exceeding threshold amounts (e.g., ₹5,000) mandate attaching a valid receipt document [9, 16].
- Approved expenses cannot be edited, only cancelled by Admin [9, 16].

### Edge Cases
- Manager rejects claim -> Mandatory reason text field required and logged [9, 16].

### Testing Requirements
- Unit test for threshold bill mandatory validation rule.
- E2E test for submitting expense claim through manager approval to accounts reimbursement.

### Completion Criteria
```text
Phase is complete when:
- Expense claims save with bill attachments and transition through approval stages correctly.
- Reimbursements log payment transaction references accurately.
```

---

## 25. Cross-Phase Dependencies

The following matrix documents inter-phase functional dependencies [30, 37]:

| Dependent Feature | Direct Dependency | Phase | Rationale |
| :--- | :--- | :--- | :--- |
| **RBAC Enforcement** | Auth & User Tables | Phase 3 | Cannot grant permissions without users and roles established [1, 14]. |
| **Lead Duplicate Match** | Lead Ingestion Service | Phase 4 | Requires phone/email extraction pipeline during ingestion [19]. |
| **Call Queue Builder** | Lead Qualification & Assign | Phase 6 | Call queue filters leads by owner and follow-up status [20, 21]. |
| **Site Visit Scheduling** | Lead Profile & Exec Roles | Phase 7 | Visits require valid lead ID and executive user ID [22]. |
| **Plot Hold Countdown** | Redis Lock Manager | Phase 8 | Real-time hold expiration requires key-value TTL locks [23, 24]. |
| **Booking Creation** | Plot Available + Customer | Phase 9 | Plot must be free and customer record active [2, 23]. |
| **Customer 360° Profile** | Booking, Payment, Docs | Phase 10 | Profile aggregates timeline across operational tables [3]. |
| **Payment Collection** | Booking Dues Schedule | Phase 11 | Payments allocate money against booking due entries [4]. |
| **eKYC Verification** | Customer Profile & S3 | Phase 12 | Requires customer record and file storage setup [5]. |
| **Registry Completion** | Zero Dues + eKYC Valid | Phase 13 | Legal deed requires full payment and verified ID [5, 7]. |
| **Communication Rules** | Event Gateway & Templates | Phase 14 | Auto-triggers fire upon status changes across modules [10]. |
| **Expenses Approvals** | Employee HR Directory | Phase 16 | Manager approval route relies on HR reporting hierarchy [9, 15, 16]. |

---

## 26. Backend / Frontend Dependency

Development phases follow specific execution strategies [36]:

```text
Backend API Contracts
       ↓
OpenAPI / Swagger Definition
       ↓
Frontend Mocking & Integration
       ↓
End-to-End Workflow Verification
```

### Phase Execution Coupling

1. **Phase 0 to Phase 3 (Foundation, Auth, RBAC)**: **Backend First**. Authentication security models, JWT contracts, and permission middlewares must exist before frontend route guards can be wired.
2. **Phase 4 & Phase 5 (Leads Acquisition & Management)**: **Parallel**. API contracts for lead endpoints defined first; frontend builds list tables and filters with mock data while backend builds CSV parsers and Meta webhooks.
3. **Phase 8 & Phase 9 (Plot Inventory & Bookings)**: **Backend + Frontend Together**. High-concurrency state transitions (holding plot, pre-booking availability re-checks) require real-time client-server socket or lock validation integration.
4. **Phase 11 (Payments & Ledger)**: **Backend First**. Strict double-entry ledger calculation logic and transaction models must be thoroughly unit-tested before frontend integration.

---

## 27. Database Dependency

The database schema must be applied sequentially according to relational foreign key hierarchies [31, 34]:

```text
Level 1: Core System Tables
   ├── organizations
   ├── projects
   └── master_data_items

Level 2: User & Role Tables
   ├── roles
   ├── users (FK -> roles)
   └── permissions (FK -> roles)

Level 3: Domain Base Entities
   ├── plots (FK -> projects)
   ├── leads (FK -> projects, users, master_data)
   └── employees (FK -> users)

Level 4: Operational Workflow Tables
   ├── site_visits (FK -> leads, users)
   ├── call_logs (FK -> leads, users)
   └── bookings (FK -> projects, leads, plots, users)

Level 5: Financial & Compliance Tables
   ├── customers (FK -> leads)
   ├── payments (FK -> bookings, customers)
   ├── customer_documents (FK -> customers)
   └── registries (FK -> plots, customers)

Level 6: Audit & Analytics
   ├── audit_logs (FK -> users)
   └── communication_logs (FK -> templates)
```

---

## 28. API Dependency

API routes rely on a shared middleware pipeline [34, 36]:

```text
Incoming HTTP Request
       │
       ▼
[ CORS / Rate Limiting Middleware ]
       │
       ▼
[ Authentication Middleware (JWT Validation) ]
       │
       ▼
[ Project Context Middleware (X-Project-ID Header) ]
       │
       ▼
[ RBAC Permission Guard (e.g., leads:create) ]
       │
       ▼
[ Input Schema Validation (Zod / Joi) ]
       │
       ▼
[ Controller / Service Logic Execution ]
       │
       ▼
[ Audit Logging Interceptor ]
       │
       ▼
HTTP Response
```

---

## 29. Risk Analysis

The following matrix identifies high-risk areas along with recommended mitigation strategies [37, 38]:

```text
Risk 1: Double-Booking / Plot Race Condition
Impact: Critical
Why it is risky: Multiple executives showing plots simultaneously might book the same plot concurrently.
Recommended mitigation: Implement Redis distributed locks during plot selection and database SELECT FOR UPDATE transactions during booking creation [23, 24].

Risk 2: Financial Ledger Integrity Corruption
Impact: Critical
Why it is risky: Manual payment edits or unverified deletion could corrupt cash flow reports and ledger balances.
Recommended mitigation: Enforce double-entry accounting rules; forbid UPDATE/DELETE on payment rows. Require explicit credit/debit adjustment records for fixes [4].

Risk 3: Uncontrolled CSV Lead Import Memory Spikes
Impact: High
Why it is risky: Uploading large CSV files (e.g., 50,000 rows) could crash node processes via memory exhaustion.
Recommended mitigation: Process CSV uploads asynchronously using stream-parsing workers (BullMQ) in 500-row chunks [19].

Risk 4: Third-Party eKYC API Downtime
Impact: Medium
Why it is risky: External UIDAI/NSDL provider outages could freeze customer onboarding.
Recommended mitigation: Implement circuit-breaker pattern with fallback to manual document upload and queue-for-later verification [5].

Risk 5: Misconfigured RBAC Data Leaks
Impact: High
Why it is risky: Telecallers seeing company-wide revenue or other executives' customer PII data.
Recommended mitigation: Enforce row-level tenant/owner checks in backend ORM middleware (`WHERE owner_id = current_user.id`) [1, 14].
```

---

## 30. Technical Debt

Legacy architectural debt and recommended preventative measures [39]:

### Critical
- **Missing Row-Level Security Guards**: Prevent query execution without `organization_id` and `project_id` scoping parameters.
- **Unencrypted Customer PII**: Mandatory AES-256 encryption at rest for customer national IDs (Aadhaar, PAN) and financial receipts [5].

### High
- **Hardcoded Master Data Choices**: Avoid string literals in code (`status == 'AVAILABLE'`); bind strictly to dynamic database master data lookups [14].
- **Unbounded Dashboard Queries**: Raw `COUNT(*)` queries on unindexed tables will slow down dashboards as lead count grows past 100k. Add composite database indexes on `(project_id, status_id, created_at)` [11, 18].

### Medium
- **Duplicate Form Validation**: Synchronize frontend validation schemas (Zod) with backend API request schemas via shared TypeScript packages.

---

## 31. Open Questions / Requirement Gaps

Identified requirement gaps requiring stakeholder confirmation [38]:

```text
Question 1: Are Registry Management (Part 15) and Expenses Tracker (Part 16/17) active project requirements?
Why it matters: Source images 15 and 17 have filenames appended with '_not_implementing.png', whereas wireframe specification sheets detail full UI flows [7, 9].
Affected phase: Phase 13 & Phase 16.
Recommended default: Treat both as active functional phases in roadmap, but defer implementation until Phase 12 completion [7, 9].

Question 2: What is the exact payment gateway provider for online collections?
Why it matters: Integration requirements vary between Razorpay, Cashfree, and Paytm.
Affected phase: Phase 11 (Payments) [4].
Recommended default: Implement payment gateway abstraction wrapper supporting Razorpay / UPI intent flows [4].

Question 3: Is eKYC integration mandatory for booking or only prior to registry?
Why it matters: Mandating eKYC at booking step increases friction during customer lead conversion.
Affected phase: Phase 9 & Phase 12 [2, 5].
Recommended default: Allow booking creation with basic ID document upload, requiring full eKYC verification prior to registry deed execution [2, 5, 7].
```

---

## 32. Recommended Implementation Order

The strategic implementation roadmap progresses through 5 master milestones [32, 40]:

```text
Milestone 1: Platform Core (Phases 0 - 3)
Phase 0 (Foundation) -> Phase 1 (Auth) -> Phase 2 (Context & Settings) -> Phase 3 (RBAC)
Rationale: Establishes repository, security, project context, and user permissions required by all modules [1, 12, 14].

Milestone 2: Sales Pipeline Ingestion (Phases 4 - 7)
Phase 4 (Lead Acquisition) -> Phase 5 (Lead Management) -> Phase 6 (Telecalling) -> Phase 7 (Site Visits)
Rationale: Enables capturing leads, qualifying them, running telecalling queues, and executing property site visits [19, 20, 21, 22].

Milestone 3: Plot Inventory & Booking Execution (Phases 8 - 10)
Phase 8 (Plot Inventory) -> Phase 9 (Booking Management) -> Phase 10 (Customer 360)
Rationale: Unlocks core business revenue generation—holding plots, booking plots, and converting leads to customer profiles [2, 3, 23, 24].

Milestone 4: Financial Ledger & Compliance (Phases 11 - 14)
Phase 11 (Payments) -> Phase 12 (eKYC Docs) -> Phase 13 (Registry) -> Phase 14 (Communication Engine)
Rationale: Manages money collection, identity compliance, plot registration, and automated customer messaging [4, 5, 7, 10].

Milestone 5: Operations & Intelligence (Phases 15 - 18)
Phase 15 (Mini-HRMS) -> Phase 16 (Expenses)
Rationale: Internal HR and expense management [8, 9, 15, 16].
```

---

## 33. Final Dependency Map

```text
                               ┌────────────────────────┐
                               │   Phase 0: Foundation  │
                               └───────────┬────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │     Phase 1: Auth      │
                               └───────────┬────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │    Phase 2: Context    │
                               └───────────┬────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │     Phase 3: RBAC      │
                               └───────────┬────────────┘
                                           │
       ┌───────────────────────────────────┼───────────────────────────────────┐
       │                                   │                                   │
       ▼                                   ▼                                   ▼
┌───────────────┐                 ┌─────────────────┐                 ┌─────────────────┐
│ Phase 4: Leads│                 │ Phase 8: Plots  │                 │ Phase 15: HRMS  │
└──────┬────────┘                 └────────┬────────┘                 └────────┬────────┘
       │                                   │                                   │
       ▼                                   │                                   ▼
┌───────────────┐                          │                          ┌─────────────────┐
│ Phase 5: Qual │                          │                          │Phase 16: Expenses│
└──────┬────────┘                          │                          └────────┬────────┘
       │                                   │                                   │
       ├─────────────────┐                 │                                   │
       ▼                 ▼                 │                                   │
┌───────────────┐ ┌───────────────┐        │                                   │
│ Phase 6: Call │ │ Phase 7: Visit│        │                                   │
└──────┬────────┘ └──────┬────────┘        │                                   │
       │                 │                 │                                   │
       └────────┬────────┘                 │                                   │
                │                          │                                   │
                ▼                          ▼                                   │
             ┌──────────────────────────────────┐                              │
             │     Phase 9: Booking Engine      │                              │
             └─────────────────┬────────────────┘                              │
                               │                                               │
                               ▼                                               │
             ┌──────────────────────────────────┐                              │
             │   Phase 10: Customer Profile     │                              │
             └─────────────────┬────────────────┘                              │
                               │                                               │
               ┌───────────────┴───────────────┐                               │
               ▼                               ▼                               │
    ┌─────────────────────┐         ┌─────────────────────┐                    │
    │  Phase 11: Payments │         │  Phase 12: eKYC Docs│                    │
    └──────────┬──────────┘         └──────────┬──────────┘                    │
               │                               │                               │
               └───────────────┬───────────────┘                               │
                               │                                               │
                               ▼                                               │
                    ┌─────────────────────┐                                    │
                    │  Phase 13: Registry │                                    │
                    └──────────┬──────────┘                                    │
                               │                                               │
                               ▼                                               │
                    ┌─────────────────────┐                                    │
                    │ Phase 14: Comm Engine│                                   │
                    └──────────┬──────────┘                                    │
                               │                                               │
                               └───────────────────────┬───────────────────────┘
                                                       │
                                                       ▼
                                            ┌─────────────────────┐
                                            └──────────┬──────────┘
                                                       │
                                                       ▼
                                            ┌─────────────────────┐
                                            └─────────────────────┘
```

---

## 34. Definition of Done

A development phase is formally considered **Complete** when all the following criteria are met [35]:

```text
Phase is complete when:

- All required REST / GraphQL backend API endpoints are implemented and documented with OpenAPI / Swagger specs.
- Database migrations are applied, verified, and backward-compatible without data loss.
- Frontend user interfaces match low-fidelity wireframe component layouts and visual states.
- Role-based access control (RBAC) permissions are enforced on both API routes and UI components.
- Primary end-to-end user workflows execute successfully without breaking errors.
- Input validations and error handling states display user-friendly notifications.
- Automated unit tests achieves >80% code coverage across core business logic services.
- Integration tests pass for high-risk transactional workflows (e.g., plot holding, payment logging).
- Audit logs capture all mutation actions performed during execution.
```

---

## 35. Final Engineering Recommendations

Key technical best practices for implementation engineers and coding agents [42, 43, 44]:

1. **State Machine Integrity**: Use strict state machine libraries (e.g., XState) for complex lifecycle flows (Leads, Bookings, Plots, Expenses) to prevent invalid state transitions [2, 9, 20, 23].
2. **Database Transaction Management**: Always wrap multi-entity state updates (e.g., Booking creation + Plot status mutation + Initial Payment entry) inside explicit ACID database transactions (`BEGIN TRANSACTION ... COMMIT`) [2, 4, 23].
3. **Idempotency Headers**: Require unique `X-Idempotency-Key` headers on all payment collection, plot locking, and booking creation APIs to prevent double charges caused by retried network requests [2, 4].
4. **Structured API Responses**: Standardize all JSON responses across endpoints:
   ```json
   {
     "success": true,
     "data": {},
     "error": null,
     "meta": { "timestamp": "2026-09-11T11:00:00Z", "project_id": "PRJ-001" }
   }
   ```
5. **Observability & Health Checks**: Expose Prometheus metrics endpoints (`/metrics`) monitoring HTTP response latency, DB pool utilization, and background job queue depth.
