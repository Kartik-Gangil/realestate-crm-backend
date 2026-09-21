# Real Estate CRM Backend - Complete API Documentation

> **Stack:** Django 6.0.7 + DRF 3.17.1 + SQLite + Token Auth
> **Python:** >= 3.13
> **Base URL:** `http://localhost:8000/api/`

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Authentication](#2-authentication)
3. [Users Module](#3-users-module-apiauth)
4. [Organizations Module](#4-organizations-module-api)
5. [Employee Management](#5-employee-management)
6. [HR Module](#6-hr-module)
7. [Leads Module](#7-leads-module)
8. [Site Visits Module](#8-site-visits-module)
9. [Inventory Module](#9-inventory-module)
10. [Documents Module](#10-documents-module)
11. [System Settings Module](#11-system-settings-module)
12. [Bad Practices & Issues](#12-bad-practices--issues)

---

## 1. Project Structure

```
Backend/
├── config/                    # Django project settings
│   ├── settings.py
│   ├── urls.py               # Root URL configuration
│   ├── wsgi.py
│   └── asgi.py
├── users/                     # Authentication & user management
├── organizations/             # Organization, membership, employees, HR
├── leads/                     # Leads, follow-ups, site visits
├── inventory/                 # Plots, bookings, payments, agreements
├── documents/                 # Document management & verification
├── system_settings/           # Platform admin, org settings, integrations
├── manage.py
├── pyproject.toml
└── db.sqlite3
```

### Root URL Configuration (`config/urls.py`)

| Prefix | App | Description |
|--------|-----|-------------|
| `admin/` | Django Admin | Admin panel |
| `api/auth/` | users | Authentication endpoints |
| `api/` | organizations | Platform admin + org membership |
| `api/settings/` | system_settings | Platform-level settings |
| `api/organizations/<slug>/settings/` | system_settings | Org-level settings |
| `api/organizations/<slug>/` | leads | Leads, follow-ups, site visits |
| `api/organizations/<slug>/` | inventory | Plots, bookings, payments |
| `api/organizations/<slug>/` | documents | Document management |

---

## 2. Authentication

- **Method:** Token Authentication (`rest_framework.authentication.TokenAuthentication`)
- **Default Permission:** `IsAuthenticated`
- Token returned on register/login in response body as `token`

---

## 3. Users Module (`api/auth/`)

### 3.1 Register

```
POST /api/auth/register/
```

**Auth:** AllowAny

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepass123",
  "first_name": "John",
  "last_name": "Doe"
}
```

**Response 201:**
```json
{
  "token": "abc123...",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "is_active": true,
    "date_joined": "2026-01-01T00:00:00Z",
    "organization_memberships": []
  }
}
```

---

### 3.2 Login

```
POST /api/auth/login/
```

**Auth:** AllowAny

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepass123"
}
```

**Response 200:**
```json
{
  "token": "abc123...",
  "user": { ... }
}
```

---

### 3.3 Logout

```
POST /api/auth/logout/
```

**Auth:** IsAuthenticated

**Request Body:** None

**Response 204:** Empty

---

### 3.4 Get Current User

```
GET /api/auth/me/
```

**Auth:** IsAuthenticated

**Response 200:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "is_active": true,
  "is_staff": false,
  "is_superuser": false,
  "last_login": "2026-01-01T00:00:00Z",
  "date_joined": "2026-01-01T00:00:00Z",
  "organization_memberships": [
    {
      "id": 1,
      "organization": "my-org",
      "organization_name": "My Organization",
      "role": "admin",
      "permissions": ["leads.view", "leads.edit", "..."]
    }
  ]
}
```

---

### 3.5 Forgot Password

```
POST /api/auth/forgot-password/
```

**Auth:** AllowAny

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Response 200:**
```json
{
  "detail": "If an active account uses this email, a password reset link has been sent."
}
```

---

### 3.6 Reset Password

```
POST /api/auth/reset-password/
```

**Auth:** AllowAny

**Request Body:**
```json
{
  "uid": "base64-encoded-uid",
  "token": "password-reset-token",
  "new_password": "newsecurepass123"
}
```

**Response 200:**
```json
{
  "detail": "Password has been reset."
}
```

**Error 400:**
```json
{
  "token": ["Invalid or expired token"],
  "new_password": ["This password is too short."]
}
```

---

### 3.7 Change Password

```
POST /api/auth/change-password/
```

**Auth:** IsAuthenticated

**Request Body:**
```json
{
  "old_password": "currentpass",
  "new_password": "newsecurepass123"
}
```

**Response 200:**
```json
{
  "detail": "Password has been changed."
}
```

---

## 4. Organizations Module (`api/`)

### 4.1 Platform Admins (Super Admin Only)

```
GET  /api/platform/admins/
POST /api/platform/admins/
```

**Auth:** IsAuthenticated + SuperAdmin

**POST Request Body:**
```json
{
  "email": "admin@example.com"
}
```

**Response 200:**
```json
{
  "id": 1,
  "email": "admin@example.com",
  "is_platform_admin": true
}
```

---

### 4.2 Platform Organizations

```
GET  /api/platform/organizations/
POST /api/platform/organizations/
```

**Auth:** IsAuthenticated + PlatformAdmin

**POST Request Body:**
```json
{
  "name": "My Organization",
  "slug": "my-org",
  "organization_admin_email": "admin@example.com"
}
```

**Response 201:**
```json
{
  "id": 1,
  "name": "My Organization",
  "slug": "my-org",
  "is_active": true,
  "created_at": "2026-01-01T00:00:00Z"
}
```

---

### 4.3 Platform Organization Access

```
POST /api/platform/organizations/<slug>/access/
```

**Auth:** IsAuthenticated + SuperAdmin

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Response 200/201:**
```json
{
  "organization": "my-org",
  "email": "user@example.com"
}
```

---

### 4.4 Organization Members

```
GET  /api/organizations/<slug>/members/
POST /api/organizations/<slug>/members/
```

**Auth:** IsAuthenticated + OrgMember

**POST Request Body:**
```json
{
  "email": "member@example.com",
  "role": "telecaller"
}
```

**Role choices:** `admin`, `manager`, `telecaller`

**Response 201:**
```json
{
  "id": 1,
  "user_id": 5,
  "email": "member@example.com",
  "name": "John Doe",
  "role": "telecaller",
  "organization_role": 3,
  "is_active": true,
  "joined_at": "2026-01-01T00:00:00Z"
}
```

---

### 4.5 My Tab Permissions

```
GET /api/organizations/<slug>/my-tab-permissions/
```

**Auth:** IsAuthenticated + OrgMember

**Response 200:**
```json
{
  "organization": "my-org",
  "role": "admin",
  "available_tabs": ["leads", "inventory", "documents", "settings"],
  "permissions": ["leads.view", "leads.edit", "plots.view", "..."]
}
```

---

## 5. Employee Management

All employee endpoints are prefixed with:
`/api/organizations/<slug:organization_slug>/`

### 5.1 Employee List & Create

```
GET  /employees/
POST /employees/
```

**Auth:** IsAuthenticated + OrgMember

**GET Query Params:** `status`, `department`, `designation`, `search`, `ordering`, `page`, `page_size`

**POST Request Body:**
```json
{
  "email": "employee@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "temporary_password": "securepass123",
  "role": "telecaller",
  "department": 1,
  "designation": "Senior Telecaller",
  "access_scope": "all",
  "mobile_number": "+91-9876543210",
  "date_of_joining": "2026-01-15",
  "employment_type": "full_time",
  "salary": 50000.00,
  "work_location": "office",
  "reporting_manager": 1,
  "custom_scope_memberships": [1, 2, 3],
  "custom_scope_departments": [1, 2]
}
```

**Response 201:**
```json
{
  "id": 1,
  "employee_id": "EMP001",
  "name": "John Doe",
  "email": "employee@example.com",
  "department": "Sales",
  "designation": "Senior Telecaller",
  "role": "telecaller",
  "status": "active",
  "date_of_joining": "2026-01-15",
  "employment_type": "full_time",
  "salary": 50000.00,
  "mobile_number": "+91-9876543210",
  "reporting_manager": "Jane Smith",
  "access_scope": "all",
  "created_at": "2026-01-15T00:00:00Z"
}
```

---

### 5.2 Employee Detail

```
GET   /employees/<id>/
PATCH /employees/<id>/
```

**Auth:** IsAuthenticated + OrgMember

**PATCH Request Body:** Any subset of employee fields

**Response:** Full employee dict (same as create response)

---

### 5.3 Employee Activate

```
POST /employees/<id>/activate/
```

**Auth:** IsAuthenticated + `employees.edit` permission

**Response 200:** Updated employee dict

**Error 400:**
```json
{
  "status": ["Employee is already active."]
}
```

---

### 5.4 Employee Deactivate

```
POST /employees/<id>/deactivate/
```

**Auth:** IsAuthenticated + `employees.edit` permission

**Response 200:** Updated employee dict

---

### 5.5 Employee Reset Password

```
POST /employees/<id>/reset-password/
```

**Auth:** IsAuthenticated + `settings.edit` permission

**Request Body:**
```json
{
  "temporary_password": "newsecurepass123"
}
```

**Response 204:** Empty

---

### 5.6 Employee Activity History

```
GET /employees/<id>/activity-history/
```

**Auth:** IsAuthenticated + OrgMember

**GET Query Params:** `page`, `page_size`

**Response 200:**
```json
{
  "count": 10,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": 1,
      "action": "create",
      "module": "employee",
      "details": {},
      "performed_by": "admin@example.com",
      "created_at": "2026-01-15T00:00:00Z"
    }
  ]
}
```

---

### 5.7 Departments

```
GET  /departments/
POST /departments/
```

**Auth:** IsAuthenticated + OrgMember

**POST Request Body:**
```json
{
  "name": "Sales",
  "code": "SALES",
  "description": "Sales department"
}
```

**Response 201:**
```json
{
  "id": 1,
  "name": "Sales",
  "code": "SALES",
  "description": "Sales department",
  "is_active": true,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

---

### 5.8 Department Detail

```
GET   /departments/<id>/
PATCH /departments/<id>/
```

**Auth:** IsAuthenticated + OrgMember

**PATCH Request Body:** `{ "name": "New Name" }` (any subset)

---

## 6. HR Module

All HR endpoints are prefixed with:
`/api/organizations/<slug:organization_slug>/`

### 6.1 Roles

```
GET    /roles/
POST   /roles/
GET    /roles/<id>/
PATCH  /roles/<id>/
PUT    /roles/<id>/
DELETE /roles/<id>/
```

**Auth:** IsAuthenticated + `settings.edit` for create/update/delete

**POST Request Body:**
```json
{
  "name": "Sales Manager",
  "code": "SALES_MGR",
  "permission_ids": [1, 2, 3, 4, 5]
}
```

**Response 201:**
```json
{
  "id": 1,
  "name": "Sales Manager",
  "code": "SALES_MGR",
  "is_system": false,
  "permissions": ["leads.view", "leads.edit", "..."]
}
```

**DELETE Request Body:**
```json
{
  "confirmation": true
}
```

**DELETE Error 409:**
```json
{
  "role": "Reassign employees before deleting this role."
}
```

---

### 6.2 Permissions

```
GET /permissions/
```

**Auth:** IsAuthenticated

**Response 200:**
```json
[
  {"id": 1, "module": "leads", "action": "view", "name": "View Leads"},
  {"id": 2, "module": "leads", "action": "edit", "name": "Edit Leads"},
  "..."
]
```

---

### 6.3 Holidays

```
GET  /holidays/
POST /holidays/
```

**Auth:** IsAuthenticated + `settings.edit` for create

**POST Request Body:**
```json
{
  "name": "Republic Day",
  "holiday_date": "2026-01-26"
}
```

**Response 201:**
```json
{
  "id": 1,
  "name": "Republic Day",
  "holiday_date": "2026-01-26",
  "source": "manual"
}
```

---

### 6.4 Attendance

```
GET  /attendance/
POST /attendance/check-in/
POST /attendance/check-out/
```

**Auth:** IsAuthenticated

**GET Query Params:** `date`, `status`, `employee`, `department`, `date_from`, `date_to`, `page`, `page_size`

**Response 200:**
```json
{
  "count": 50,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": 1,
      "employee": 1,
      "attendance_date": "2026-01-26",
      "check_in": "2026-01-26T09:00:00+05:30",
      "check_out": "2026-01-26T18:00:00+05:30",
      "total_hours": 9.0,
      "status": "present"
    }
  ]
}
```

**POST check-in Request Body:**
```json
{
  "employee": 1
}
```

**Response 201:** Attendance record

---

### 6.5 Leaves

```
GET    /leaves/
POST   /leaves/
GET    /leaves/<id>/
PATCH  /leaves/<id>/
POST   /leaves/<id>/approve/
POST   /leaves/<id>/reject/
POST   /leaves/<id>/cancel/
```

**Auth:** IsAuthenticated

**POST Request Body:**
```json
{
  "employee": 1,
  "leave_type": "casual",
  "from_date": "2026-02-01",
  "to_date": "2026-02-03",
  "reason": "Family function"
}
```

**Leave types:** `casual`, `sick`, `earned`

**POST approve/reject/cancel:** No body required for approve/cancel

**POST reject Request Body (optional):**
```json
{
  "rejection_reason": "Insufficient coverage"
}
```

---

## 7. Leads Module

All leads endpoints are prefixed with:
`/api/organizations/<slug:organization_slug>/`

### 7.1 Lead List & Create

```
GET  /leads/
POST /leads/
```

**Auth:** IsAuthenticated + `leads.edit` for create

**GET Query Params:** `status`, `source`, `search`

**POST Request Body:**
```json
{
  "first_name": "Rahul",
  "phone": "+91-9876543210",
  "source": "website",
  "last_name": "Sharma",
  "email": "rahul@example.com",
  "assigned_membership": 1,
  "alt_phone": "+91-9876543211",
  "address": "123 Main St, Mumbai",
  "occupation": "Engineer"
}
```

**Source choices:** `walk_in`, `reference`, `website`, `social_media`, `property_portal`, `cold_call`, `newspaper`, `other`

**Response 201:**
```json
{
  "id": 1,
  "first_name": "Rahul",
  "last_name": "Sharma",
  "phone": "+91-9876543210",
  "email": "rahul@example.com",
  "source": "website",
  "status": "new",
  "assigned_membership": 1,
  "assigned_membership_name": "John Doe",
  "created_at": "2026-01-01T00:00:00Z",
  "latest_follow_up_status": null
}
```

---

### 7.2 Lead Detail

```
GET    /leads/<id>/
PATCH  /leads/<id>/
PUT    /leads/<id>/
DELETE /leads/<id>/
```

**Auth:** IsAuthenticated

**GET Response:** Lead dict + `follow_ups` list

**PATCH Request Body:** Any subset of lead fields

**PUT Request Body (full update):**
```json
{
  "first_name": "Rahul",
  "phone": "+91-9876543210",
  "source": "website"
}
```

**DELETE:** Requires `leads.edit` permission

**Response 204:** Empty

---

### 7.3 Import Leads CSV

```
POST /leads/import/
```

**Auth:** IsAuthenticated + `leads.edit`

**Request:** `multipart/form-data`

| Field | Type | Description |
|-------|------|-------------|
| `file` | File | CSV, XLS, or XLSX file |

**Required CSV columns:** `first_name` (or `full_name`) and `phone`

**Response 201:**
```json
{
  "imported": 10,
  "results": [
    {"row": 1, "status": "created", "lead_id": 1},
    {"row": 2, "status": "skipped", "reason": "Duplicate phone"}
  ]
}
```

---

### 7.4 Assigned Leads

```
GET /leads/assigned/
```

**Auth:** IsAuthenticated (telecallers only)

**Response 200:**
```json
{
  "count": 5,
  "results": [
    { "id": 1, "first_name": "Rahul", "phone": "+91-9876543210", "..." : "..." }
  ]
}
```

---

### 7.5 Bulk Reset Assignments

```
PATCH /leads/bulk_reset/
```

**Auth:** IsAuthenticated + `leads.edit`

**Response 200:**
```json
{
  "message": "All lead assignments have been reset.",
  "updated_count": 15
}
```

---

### 7.6 Assign Leads Round Robin

```
POST /leads/assign-round-robin/
```

**Auth:** IsAuthenticated + `leads.edit`

**Request Body:**
```json
{
  "lead_ids": [1, 2, 3]
}
```

**Response 201:**
```json
{
  "assigned": 3,
  "results": [
    {"lead_id": 1, "telecaller": "John Doe", "membership_id": 1},
    {"lead_id": 2, "telecaller": "Jane Smith", "membership_id": 2},
    {"lead_id": 3, "telecaller": "John Doe", "membership_id": 1}
  ]
}
```

---

### 7.7 Assign Single Lead

```
PATCH /leads/<id>/assign/
```

**Auth:** IsAuthenticated + `leads.edit`

**Request Body:**
```json
{
  "telecaller_membership": 1
}
```

**Response:** Updated lead dict

---

### 7.8 Lead Dashboard

```
GET /leads/dashboard/
GET /dashboard/
```

**Auth:** IsAuthenticated

**Response 200:**
```json
{
  "organization": "my-org",
  "total_leads": 150,
  "by_status": {
    "new": 30,
    "contacted": 50,
    "qualified": 40,
    "converted": 20,
    "lost": 10
  },
  "by_source": {
    "website": 60,
    "reference": 40,
    "walk_in": 30,
    "other": 20
  },
  "recent_follow_up_calls": [
    {
      "id": 1,
      "lead_name": "Rahul Sharma",
      "outcome": "interested",
      "called_at": "2026-01-26T10:30:00Z"
    }
  ]
}
```

---

### 7.9 Lead Summary

```
GET /leads/summary/
GET /summary/
```

**Auth:** IsAuthenticated

**Response 200:**
```json
{
  "total": 150,
  "by_status": {
    "new": 30,
    "contacted": 50,
    "qualified": 40,
    "converted": 20,
    "lost": 10
  }
}
```

---

### 7.10 Scheduled Follow-Ups

```
GET  /leads/<id>/follow-ups/
POST /leads/<id>/follow-ups/
```

**Auth:** IsAuthenticated

**GET Query Params:** `status`

**POST Request Body:**
```json
{
  "note": "Call the customer tomorrow",
  "status": "new",
  "next_follow_up": "2026-02-01T10:00:00Z"
}
```

Completed-call fields such as `disposition`, `outcome`, `called_at`, and
`call_timestamp` are rejected here. Use API-P6-06 below to record call activity.

**Response 201:** Follow-up dict

The equivalent organization-level contract endpoint is:

```
POST /api/v1/organizations/<slug>/telecalling/follow-ups/
```

It accepts `lead_id`, `note`, and `next_follow_up`.

---

### 7.11 Manual Call Log (API-P6-06)

```
POST /api/v1/organizations/<slug>/telecalling/calls/log/
```

**Auth:** IsAuthenticated + assigned Telecaller

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `lead_id` | Integer | Yes | Lead assigned to the authenticated telecaller |
| `disposition` | String | Yes | Active Phase 6 master-data disposition code |
| `notes` | String | Yes | Manual notes from the completed external call |
| `call_timestamp` | ISO-8601 datetime | No | Defaults to submission time; may be edited |
| `next_follow_up` | ISO-8601 datetime | Conditional | Required for `interested` and `callback_later` |
| `call_recording` | File | No | MP3, WAV, M4A, or AAC; maximum 25 MB |

**Response 201/200:**

```json
{
  "id": 42,
  "lead_id": 10,
  "caller": {"id": 7, "user_id": 12, "role": "telecaller"},
  "disposition": "callback_later",
  "notes": "Customer requested a call tomorrow.",
  "call_timestamp": "2026-09-17T12:30:00+05:30",
  "call_recording_url": "http://localhost:8000/media/call-recordings/org/1/example.m4a",
  "next_follow_up": "2026-09-18T11:00:00+05:30",
  "created_at": "2026-09-17T12:30:00+05:30"
}
```

The obsolete `/telecalling/calls/start/` and `/telecalling/calls/end/` routes
are not available. Calls occur outside the CRM and API-P6-06 is the sole
completed-call activity writer.

---

## 8. Site Visits Module

All site visit endpoints are prefixed with:
`/api/organizations/<slug:organization_slug>/`

### 8.1 Site Visit List & Create

```
GET  /sitevisits/
POST /sitevisits/
```

**Auth:** IsAuthenticated

**GET Query Params:** `date`, `start_date`, `end_date`, `month`, `status`, `lead`, `executive`, `site`

**POST Request Body:**
```json
{
  "lead": 1,
  "visit_date": "2026-02-01",
  "visit_time": "10:00:00",
  "site": "Mumbai Central",
  "location": "Tower A, 15th Floor",
  "customer_preference": "2BHK with sea view",
  "notes": "Customer prefers morning slot"
}
```

**Response 201:**
```json
{
  "id": 1,
  "lead": 1,
  "lead_name": "Rahul Sharma",
  "executive": 1,
  "executive_name": "John Doe",
  "visit_date": "2026-02-01",
  "visit_time": "10:00:00",
  "duration_minutes": 60,
  "site": "Mumbai Central",
  "location": "Tower A, 15th Floor",
  "status": "scheduled",
  "outcome": null,
  "interest_level": null,
  "customer_preference": "2BHK with sea view",
  "notes": "Customer prefers morning slot",
  "reschedule_history": [],
  "created_at": "2026-01-26T00:00:00Z"
}
```

---

### 8.2 Site Visit Detail

```
GET   /sitevisits/<id>/
PATCH /sitevisits/<id>/
```

**Auth:** IsAuthenticated

**PATCH Request Body:**
```json
{
  "visit_date": "2026-02-05",
  "visit_time": "14:00:00",
  "duration_minutes": 90,
  "executive": 2,
  "site": "Pune Central",
  "location": "Tower B",
  "customer_preference": "3BHK",
  "notes": "Rescheduled",
  "status": "upcoming",
  "reschedule_reason": "Customer request"
}
```

---

### 8.3 Reschedule Site Visit

```
POST /sitevisits/<id>/reschedule/
```

**Auth:** IsAuthenticated

**Request Body:**
```json
{
  "new_date": "2026-02-05",
  "new_time": "14:00:00",
  "reason": "Customer requested change"
}
```

**Response 201:** Reschedule dict

---

### 8.4 Cancel Site Visit

```
POST /sitevisits/<id>/cancel/
```

**Auth:** IsAuthenticated

**Request Body:**
```json
{
  "cancellation_reason": "Customer not available",
  "notes": "Will rebook next week",
  "notify_customer": true
}
```

**Response 200:** Visit dict + notification flags

---

### 8.5 No-Show

```
POST /sitevisits/<id>/no-show/
```

**Auth:** IsAuthenticated

**Request Body:**
```json
{
  "after_minutes": 30,
  "notify_executive": true
}
```

**Response 200:** Visit dict + notification flags

---

### 8.6 Record Outcome

```
POST /sitevisits/<id>/outcome/
```

**Auth:** IsAuthenticated

**Request Body:**
```json
{
  "outcome": "interested",
  "interest_level": 4,
  "remarks": "Customer liked the 2BHK layout"
}
```

**Outcome choices:** `interested`, `not_interested`, `no_show`, `cancelled`, `rescheduled`, `completed`, `pending`, `in_progress`, `scheduled`

**Interest Level:** 1-5 (1=Low, 5=High)

---

### 8.7 Site Visit History

```
GET /sitevisits/<id>/history/
```

**Auth:** IsAuthenticated

**Response 200:** Visit dict with `reschedule_history` array

---

### 8.8 Upcoming Site Visits

```
GET /sitevisits/upcoming/
```

**Auth:** IsAuthenticated

**GET Query Params:** `page`, `page_size`

**Response 200:** Paginated list of upcoming visits

---

### 8.9 Today's Site Visits

```
GET /sitevisits/today/
```

**Auth:** IsAuthenticated

**GET Query Params:** `executive` (optional)

**Response 200:**
```json
{
  "date": "2026-01-26",
  "count": 5,
  "results": [
    { "id": 1, "lead_name": "Rahul Sharma", "visit_time": "10:00:00", "..." : "..." }
  ]
}
```

---

### 8.10 Calendar View

```
GET /sitevisits/calendar/
```

**Auth:** IsAuthenticated

**GET Query Params:** `start_date` or `month` (required), plus filter params

**Response 200:**
```json
{
  "count": 10,
  "results": [
    {
      "id": 1,
      "title": "Rahul Sharma - Mumbai Central",
      "start": "2026-02-01T10:00:00",
      "status": "scheduled",
      "site": "Mumbai Central",
      "location": "Tower A"
    }
  ]
}
```

---

### 8.11 Site Visit Analytics

```
GET /sitevisits/analytics/
```

**Auth:** IsAuthenticated

**Response 200:**
```json
{
  "total_visits": 100,
  "completed": 60,
  "no_show": 15,
  "cancelled": 10,
  "average_interest_level": 3.2,
  "outcome_distribution": {
    "interested": 40,
    "not_interested": 20,
    "no_show": 15
  },
  "visits_trend": [
    {"date": "2026-01-01", "count": 5},
    "..."
  ]
}
```

---

### 8.12 Lead Site Visits

```
GET /leads/<id>/sitevisits/
```

**Auth:** IsAuthenticated

**Response 200:**
```json
{
  "lead": 1,
  "count": 3,
  "results": [
    { "id": 1, "visit_date": "2026-02-01", "status": "completed", "..." : "..." }
  ]
}
```

---

## 9. Inventory Module

All inventory endpoints are prefixed with:
`/api/organizations/<slug:organization_slug>/`

### 9.1 Blocks

```
GET  /inventory/blocks/
POST /inventory/blocks/
GET  /inventory/blocks/<id>/
PATCH /inventory/blocks/<id>/
```

**Auth:** IsAuthenticated

**POST Request Body:**
```json
{
  "name": "Tower A",
  "code": "TWR-A"
}
```

**Response 201:**
```json
{
  "id": 1,
  "name": "Tower A",
  "code": "TWR-A",
  "organization": 1,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

---

### 9.2 Plots

```
GET  /inventory/plots/
POST /inventory/plots/
GET  /inventory/plots/<id>/
PATCH /inventory/plots/<id>/
POST /inventory/plots/<id>/status/
POST /inventory/plots/<id>/block/
POST /inventory/plots/<id>/hold/
POST /inventory/plots/<id>/release/
GET  /inventory/plots/<id>/history/
POST /inventory/plots/bulk-status/
```

**Auth:** IsAuthenticated + `plots.edit` for status changes

**POST Request Body:**
```json
{
  "plot_number": "A-101",
  "block": 1,
  "size": 1200.00,
  "plot_type": "2bhk",
  "rate_per_sq_unit": 5000.00,
  "total_price": 6000000.00,
  "facing": "north",
  "dimensions": "40x30",
  "description": "Corner plot with garden view"
}
```

**Plot types:** `1bhk`, `2bhk`, `3bhk`, `4bhk`, `villa`, `plot`, `commercial`

**Status choices:** `available`, `held`, `blocked`, `booked`, `sold`, `reserved`, `maintenance`

**POST status/block/hold/release Request Body:**
```json
{
  "status": "held",
  "reason": "Customer interested",
  "from_datetime": "2026-02-01T00:00:00Z",
  "to_datetime": "2026-02-07T00:00:00Z",
  "notes": "Holding for site visit"
}
```

**POST bulk-status Request Body:**
```json
{
  "plot_ids": [1, 2, 3, 4],
  "status": "available",
  "reason": "Released from maintenance"
}
```

**Response:**
```json
{
  "updated": 4,
  "plots": [
    {"id": 1, "plot_number": "A-101", "status": "available"},
    "..."
  ]
}
```

---

### 9.3 Plot Inventory (Customer-Facing)

```
GET /inventory/plot-inventory/
GET /inventory/plot-inventory/<id>/
GET /inventory/plot-inventory/<id>/availability/
POST /inventory/plot-inventory/<id>/select/
```

**Auth:** IsAuthenticated

**GET Query Params:** `block`, `status`, `plot_type`, `search`, `facing`, `available`, `min_size`, `max_size`, `lead_id`, `site_visit_id`, `page`, `page_size`

**GET availability Response:**
```json
{
  "plot_id": 1,
  "available": true,
  "status": "available",
  "reason": null,
  "can_select_another": true
}
```

**POST select Request Body:**
```json
{
  "lead_id": 1,
  "site_visit_id": 1
}
```

---

### 9.4 Plot Selections

```
GET  /inventory/plot-selections/
GET  /inventory/plot-selections/<id>/
POST /inventory/plot-selections/<id>/confirm/
POST /inventory/plot-selections/<id>/release/
```

**Auth:** IsAuthenticated + `plots.edit` for confirm/release

**POST release Request Body:**
```json
{
  "reason": "Customer changed mind"
}
```

**confirm Response includes:**
```json
{
  "...": "...",
  "next_action": "BOOKING",
  "booking_context": {
    "plot_id": 1,
    "lead_id": 1,
    "site_visit_id": 1
  }
}
```

---

### 9.5 Bookings

```
GET  /inventory/bookings/
POST /inventory/bookings/
GET  /inventory/bookings/<id>/
POST /inventory/bookings/<id>/confirm/
POST /inventory/bookings/<id>/cancel/
GET  /inventory/leads/<id>/bookings/
GET  /inventory/plots/<id>/bookings/
```

**Auth:** IsAuthenticated + `plots.edit` for confirm/cancel

**POST Request Body:**
```json
{
  "lead_id": 1,
  "plot_id": 1,
  "site_visit_id": 1,
  "notes": "Customer confirmed after site visit"
}
```

**POST cancel Request Body:**
```json
{
  "reason": "Customer found alternative"
}
```

---

### 9.6 Payments (Legacy)

```
GET  /inventory/bookings/<id>/payments/
POST /inventory/bookings/<id>/payments/
GET  /inventory/payments/
GET  /inventory/payments/<id>/
POST /inventory/payments/<id>/confirm/
POST /inventory/payments/<id>/fail/
POST /inventory/payments/<id>/refund/
```

**Auth:** IsAuthenticated + `plots.edit` for confirm/fail/refund

**POST payment Request Body:**
```json
{
  "amount": 100000.00,
  "payment_method": "bank_transfer",
  "payment_date": "2026-02-01",
  "transaction_reference": "TXN123456",
  "notes": "Advance payment"
}
```

**POST refund Request Body:**
```json
{
  "amount": 50000.00,
  "reason": "Booking cancelled",
  "refund_date": "2026-02-15"
}
```

---

### 9.7 Installments

```
GET  /inventory/bookings/<id>/installments/
POST /inventory/bookings/<id>/installments/
GET  /inventory/installments/
GET  /inventory/installments/<id>/
PATCH /inventory/installments/<id>/
POST /inventory/installments/<id>/allocate/
```

**Auth:** IsAuthenticated + `plots.edit` for allocate

**POST installment Request Body:**
```json
{
  "installment_number": 1,
  "title": "First Installment",
  "due_date": "2026-03-01",
  "amount": 200000.00,
  "notes": "Due with agreement signing"
}
```

**POST allocate Request Body:**
```json
{
  "payment_id": 1,
  "amount": 200000.00
}
```

---

### 9.8 Agreements

```
GET  /inventory/bookings/<id>/agreement/
POST /inventory/bookings/<id>/agreement/
GET  /inventory/agreements/
GET  /inventory/agreements/<id>/
PATCH /inventory/agreements/<id>/
POST /inventory/agreements/<id>/ready/
POST /inventory/agreements/<id>/sign/
POST /inventory/agreements/<id>/cancel/
POST /inventory/agreements/<id>/generate-pdf/
GET  /inventory/agreements/<id>/download-pdf/
POST /inventory/agreements/<id>/upload-signed/
GET  /inventory/agreements/<id>/download-signed/
```

**Auth:** IsAuthenticated + `plots.edit` for ready/sign/cancel/generate-pdf/upload-signed

**POST agreement Request Body:**
```json
{
  "agreement_number": "AGR-2026-001",
  "agreement_date": "2026-02-15",
  "document_reference": "DOC-REF-123",
  "notes": "Standard agreement"
}
```

**POST generate-pdf:** No body required. Generates a PDF agreement template from the booking/plot/buyer details and stores it on the agreement record.

**GET download-pdf Response:** PDF file download (binary stream, `application/pdf`)

**POST upload-signed Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | Signed agreement PDF (PDF/JPEG/PNG) |

**GET download-signed Response:** Signed PDF file download (binary stream)

**Agreement response now includes:**
```json
{
  "id": 1,
  "booking_id": 1,
  "agreement_number": "AGR-2026-001",
  "agreement_date": "2026-02-15",
  "status": "signed",
  "document_reference": "DOC-REF-123",
  "notes": "Standard agreement",
  "has_generated_pdf": true,
  "has_signed_file": true,
  "signed_file_name": "signed_agreement.pdf"
}
```

---

### 9.9 Registries

```
GET  /inventory/bookings/<id>/registry/
POST /inventory/bookings/<id>/registry/
GET  /inventory/registries/
GET  /inventory/registries/<id>/
PATCH /inventory/registries/<id>/
POST /inventory/registries/<id>/schedule/
POST /inventory/registries/<id>/complete/
POST /inventory/registries/<id>/cancel/
GET  /inventory/registries/<id>/documents/
POST /inventory/registries/<id>/documents/
DELETE /inventory/registries/<id>/documents/<doc_id>/
```

**Auth:** IsAuthenticated + `plots.edit` for schedule/complete/cancel, `registry.documents` for document operations

**POST registry Request Body:**
```json
{
  "registry_number": "REG-2026-001",
  "registry_date": "2026-03-01",
  "sub_registrar_office": "Andheri",
  "document_type": "sale_deed",
  "consideration_amount": 6000000.00,
  "notes": "Registry scheduled"
}
```

**Registry Documents — Attach a document to a registry:**

POST Request: `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Conditional | Upload a new file (PDF/JPEG/PNG). Required if `customer_document_id` not provided. |
| `customer_document_id` | Integer | Conditional | Reference an existing eKYC document from the customer's profile. Required if `file` not provided. |
| `document_label` | String | No | Human-readable label (e.g. "Aadhaar - Buyer"). Defaults to filename or document name. |
| `document_type` | String | No | Category tag (e.g. "ekyc", "id_proof", "sale_deed"). Defaults to "ekyc" for references, "other" for uploads. |

**Note:** Provide either `file` OR `customer_document_id`, not both.

**Registry Documents — List response:**
```json
[
  {
    "id": 1,
    "registry_id": 1,
    "document_label": "Aadhaar Card",
    "document_type": "ekyc",
    "source": "reference",
    "uploaded_by": {"id": 1, "name": "Admin"},
    "created_at": "2026-03-01T00:00:00Z",
    "customer_document": {
      "id": 5,
      "document_name": "Aadhaar Card",
      "file_name": "aadhaar.pdf",
      "content_type": "application/pdf"
    }
  },
  {
    "id": 2,
    "registry_id": 1,
    "document_label": "sale_deed.pdf",
    "document_type": "sale_deed",
    "source": "upload",
    "uploaded_by": {"id": 1, "name": "Admin"},
    "created_at": "2026-03-01T00:00:00Z",
    "file": {
      "file_name": "sale_deed.pdf",
      "file_size": 102400,
      "content_type": "application/pdf"
    }
  }
]
```

---

### 9.10 Possessions

```
GET  /inventory/bookings/<id>/possession/
POST /inventory/bookings/<id>/possession/
GET  /inventory/possessions/
GET  /inventory/possessions/<id>/
PATCH /inventory/possessions/<id>/
POST /inventory/possessions/<id>/schedule/
POST /inventory/possessions/<id>/complete/
POST /inventory/possessions/<id>/cancel/
```

**Auth:** IsAuthenticated + `plots.edit` for schedule/complete/cancel

**POST possession Request Body:**
```json
{
  "possession_date": "2026-04-01",
  "notes": "Keys handed over"
}
```

---

### 9.11 Managed Payments (New Payment System)

```
GET    /payments/
POST   /payments/
GET    /payments/summary/
GET    /payments/<id>/
POST   /payments/<id>/confirm/
GET    /payments/<id>/receipt/
POST   /payments/<id>/refund/
POST   /payments/<id>/adjustment/
POST   /payments/<id>/refunds/<refund_id>/approve/
GET    /customers/<id>/payments/
GET    /customers/<id>/dues/
GET    /customers/<id>/payment-ledger/
```

**Auth:** IsAuthenticated + `payments.view`/`payments.add`/`payments.refund`/`payments.adjust`

**POST managed payment Request Body:**
```json
{
  "amount": 500000.00,
  "payment_method": "bank_transfer",
  "mode": "online",
  "payment_date": "2026-02-01",
  "transaction_reference": "NEFT-12345",
  "notes": "Advance payment for booking",
  "booking_allocations": [
    {
      "booking_id": 1,
      "amount": 300000.00,
      "installment_id": 1,
      "registry_charge_id": null
    },
    {
      "booking_id": 1,
      "amount": 200000.00,
      "installment_id": 2,
      "registry_charge_id": null
    }
  ]
}
```

**POST refund Request Body:**
```json
{
  "amount": 50000.00,
  "reason": "Overpayment correction"
}
```

**POST adjustment Request Body:**
```json
{
  "amount": 10000.00,
  "reason": "Rate correction"
}
```

**GET payment ledger Response:**
```json
{
  "customer": 1,
  "total_paid": 500000.00,
  "total_refunded": 50000.00,
  "total_adjusted": 10000.00,
  "net_paid": 460000.00,
  "transactions": [
    {"id": 1, "type": "payment", "amount": 500000.00, "date": "2026-02-01"},
    {"id": 1, "type": "refund", "amount": -50000.00, "date": "2026-02-15"}
  ]
}
```

---

### 9.12 Managed Registries

```
GET  /registries/
POST /registries/
GET  /registries/<id>/
PATCH /registries/<id>/
POST /registries/<id>/status/
GET  /registries/<id>/history/
GET  /registries/<id>/documents/
POST /registries/<id>/documents/
DELETE /registries/<id>/documents/<doc_id>/
```

**Auth:** IsAuthenticated + `registry.view`/`registry.add`/`registry.edit`/`registry.status`/`registry.documents`

**POST managed registry Request Body:**
```json
{
  "booking_id": 1,
  "registry_number": "REG-2026-001",
  "registry_date": "2026-03-01",
  "registry_time": "11:00:00",
  "sub_registrar_office": "Andheri SR",
  "document_type": "sale_deed",
  "consideration_amount": 6000000.00,
  "agreement_number": "AGR-2026-001",
  "agreement_date": "2026-02-15",
  "notes": "Registry scheduled",
  "reminder_date": "2026-02-28",
  "reminder_enabled": true
}
```

---

## 10. Documents Module

All document endpoints are prefixed with:
`/api/organizations/<slug:organization_slug>/`

### 10.1 Document List & Upload

```
GET  /documents/
POST /documents/
```

**Auth:** IsAuthenticated

**POST Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | Document file (PDF/JPEG/PNG) |
| `customer` | Integer | Yes | Lead/Customer ID |
| `document_category` | Integer | Yes | Category ID |
| `document_name` | String | Yes | Display name |
| `expiry_date` | Date | No | Document expiry date |
| `notes` | String | No | Additional notes |

**Response 201:**
```json
{
  "id": 1,
  "customer": 1,
  "document_category": 1,
  "category": {
    "id": 1,
    "name": "ID Proof",
    "code": "ID_PROOF"
  },
  "document_name": "Aadhaar Card",
  "file_name": "aadhaar.pdf",
  "file_size": 102400,
  "content_type": "application/pdf",
  "version": 1,
  "status": "uploaded",
  "expiry_date": "2027-01-01",
  "notes": "Front and back scan",
  "uploaded_by": 1,
  "uploaded_at": "2026-01-26T00:00:00Z",
  "verified_by": null,
  "verified_at": null,
  "rejection_reason": null,
  "archived_at": null,
  "created_at": "2026-01-26T00:00:00Z",
  "updated_at": "2026-01-26T00:00:00Z"
}
```

---

### 10.2 Document Detail

```
GET /documents/<id>/
```

**Auth:** IsAuthenticated

**Response:** Full document dict (same as upload response)

---

### 10.3 Document Download

```
GET /documents/<id>/download/
```

**Auth:** IsAuthenticated

**Response:** File download (binary stream)

---

### 10.4 Document History

```
GET /documents/<id>/history/
```

**Auth:** IsAuthenticated

**Response 200:**
```json
{
  "versions": [
    {"version": 1, "uploaded_at": "2026-01-26T00:00:00Z", "uploaded_by": "John Doe"},
    {"version": 2, "uploaded_at": "2026-02-01T00:00:00Z", "uploaded_by": "Jane Smith"}
  ],
  "verification_history": [
    {
      "old_status": "uploaded",
      "new_status": "under_verification",
      "reason": null,
      "changed_by": "Admin",
      "changed_at": "2026-01-27T00:00:00Z"
    },
    {
      "old_status": "under_verification",
      "new_status": "verified",
      "reason": null,
      "changed_by": "Admin",
      "changed_at": "2026-01-28T00:00:00Z"
    }
  ]
}
```

---

### 10.5 Mark Under Verification

```
POST /documents/<id>/under-verification/
```

**Auth:** IsAuthenticated + document management permission

**Response:** Updated document dict

---

### 10.6 Verify Document

```
POST /documents/<id>/verify/
```

**Auth:** IsAuthenticated + document management permission

**Response:** Updated document dict

---

### 10.7 Reject Document

```
POST /documents/<id>/reject/
```

**Auth:** IsAuthenticated + document management permission

**Request Body:**
```json
{
  "rejection_reason": "Document is expired"
}
```

**Response:** Updated document dict

---

### 10.8 Archive Document

```
POST /documents/<id>/archive/
```

**Auth:** IsAuthenticated + document management permission

**Response:** Updated document dict

---

### 10.9 Pending Verification

```
GET /documents/pending-verification/
```

**Auth:** IsAuthenticated

**Response 200:** List of documents with status `uploaded` or `under_verification`

---

### 10.10 Expiry Alerts

```
GET /documents/expiry-alerts/
```

**Auth:** IsAuthenticated

**GET Query Params:** `state` = `expired` (default) | `expiring`

**Response 200:** List of expired or expiring documents

---

### 10.11 Document Categories

```
GET  /documents/categories/
POST /documents/categories/
PATCH /documents/categories/<id>/
```

**Auth:** IsAuthenticated + document management for create/update

**POST Request Body:**
```json
{
  "name": "ID Proof",
  "code": "ID_PROOF",
  "description": "Government issued ID documents",
  "is_active": true
}
```

**Response 201:**
```json
{
  "id": 1,
  "name": "ID Proof",
  "code": "ID_PROOF",
  "description": "Government issued ID documents",
  "is_active": true,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

---

### 10.12 Customer Documents

```
GET /customers/<id>/documents/
```

**Auth:** IsAuthenticated

**Response 200:**
```json
{
  "customer": {"id": 1, "full_name": "Rahul Sharma"},
  "requirements": [
    {
      "id": 1,
      "category": {"id": 1, "name": "ID Proof", "code": "ID_PROOF"},
      "is_mandatory": true,
      "is_active": true
    }
  ],
  "documents": [
    {
      "id": 1,
      "document_name": "Aadhaar Card",
      "status": "verified",
      "category": {"id": 1, "name": "ID Proof"},
      "version": 1,
      "expiry_date": "2027-01-01"
    }
  ],
  "summary": {
    "total_requirements": 5,
    "fulfilled": 3,
    "pending": 2,
    "expired": 0
  },
  "booked_plots": [
    {
      "booking_id": 1,
      "plot": {"id": 1, "plot_number": "A-101", "block": "Tower A"},
      "status": "confirmed",
      "registry": {
        "id": 1,
        "status": "pending",
        "documents": [
          {
            "id": 1,
            "document_label": "Aadhaar Card",
            "document_type": "ekyc",
            "source": "reference",
            "customer_document_id": 5,
            "file_name": "aadhaar.pdf",
            "uploaded_by": {"id": 1, "name": "Admin"},
            "created_at": "2026-03-01T00:00:00Z"
          }
        ]
      }
    }
  ]
}
```

---

### 10.13 Customer Document Requirements

```
GET  /customers/<id>/document-requirements/
POST /customers/<id>/document-requirements/
PATCH /customers/<id>/document-requirements/<id>/
```

**Auth:** IsAuthenticated + document management for create/update

**POST Request Body:**
```json
{
  "document_category": 1,
  "is_mandatory": true,
  "is_active": true
}
```

---

### 10.14 Employee Documents

```
GET  /employees/<id>/documents/
POST /employees/<id>/documents/
```

**Auth:** IsAuthenticated

**POST Request:** `multipart/form-data` (same fields as customer document upload)

---

### 10.15 Employee Document Detail

```
GET /employee-documents/<id>/
GET /employee-documents/<id>/download/
GET /employee-documents/<id>/history/
POST /employee-documents/<id>/archive/
```

**Auth:** IsAuthenticated + document management for archive

---

## 11. System Settings Module

### 11.1 Platform-Level Settings (`api/settings/`)

All require **IsAuthenticated + PlatformAdmin**

```
GET /api/settings/overview/
GET /api/settings/organizations/
GET /api/settings/system-info/
GET /api/settings/audit-logs/
GET /api/settings/backups/
POST /api/settings/backups/
POST /api/settings/maintenance/
GET /api/settings/health-check/
POST /api/settings/health-check/
```

**POST maintenance Request Body:**
```json
{
  "confirmation": true,
  "operation": "clear_cache"
}
```

**Operation choices:** `clear_cache`, `rebuild_search_index`

**POST backups Request Body:**
```json
{
  "confirmation": true
}
```

**Response 202:** Accepted for async backup

---

### 11.2 Organization-Level Settings

All prefixed with:
`/api/organizations/<slug:organization_slug>/`

#### 11.2.1 General Settings

```
GET  /settings/general/
PATCH /settings/general/
```

**Auth:** IsAuthenticated + OrgSettings permission

**PATCH Request Body:**
```json
{
  "company_name": "My Real Estate Corp",
  "company_logo": "logo.png",
  "date_format": "DD/MM/YYYY",
  "timezone": "Asia/Kolkata",
  "currency": "INR",
  "items_per_page": 25
}
```

**Timezone validation:** IANA timezone format
**Currency validation:** 3-letter ISO alpha code, uppercased

---

#### 11.2.2 Permissions

```
GET /permissions/
```

**Auth:** IsAuthenticated + OrgMember

**Response 200:** List of all available permissions

---

#### 11.2.3 Role Mapping

```
GET    /role-mapping/
POST   /role-mapping/
PATCH  /role-mapping/<membership_id>/
```

**Auth:** IsAuthenticated + OrgSettings permission

**POST Request Body:**
```json
{
  "membership_id": 1,
  "role_id": 3,
  "confirmation": true
}
```

---

#### 11.2.4 Access Matrix

```
GET /access-matrix/
```

**Auth:** IsAuthenticated + OrgMember

**Response 200:** Full access matrix showing all roles and their permissions

---

#### 11.2.5 Integrations

```
GET  /settings/integrations/
POST /settings/integrations/
PATCH /settings/integrations/<id>/
```

**Auth:** IsAuthenticated + OrgSettings permission

**POST Request Body:**
```json
{
  "integration_type": "email",
  "name": "SMTP Config",
  "enabled": true,
  "configuration": {
    "host": "smtp.gmail.com",
    "port": 587,
    "use_tls": true
  },
  "secrets": {
    "username": "user@gmail.com",
    "password": "app-password"
  },
  "confirmation": true
}
```

**Integration types:** `email`, `sms`, `whatsapp`, `document_storage`

---

#### 11.2.6 System Parameters

```
GET    /settings/system-parameters/
POST   /settings/system-parameters/
PATCH  /settings/system-parameters/<id>/
DELETE /settings/system-parameters/<id>/
```

**Auth:** IsAuthenticated + OrgSettings permission

**POST Request Body:**
```json
{
  "parameter_key": "booking_deposit_percentage",
  "parameter_name": "Booking Deposit Percentage",
  "value": "10",
  "data_type": "decimal",
  "description": "Minimum deposit percentage for booking",
  "is_critical": true,
  "confirmation": true
}
```

**Data types:** `string`, `integer`, `decimal`, `boolean`, `json`

---

#### 11.2.7 Master Data

```
GET  /settings/masters/
GET  /settings/masters/<master_type>/
POST /settings/masters/<master_type>/
PATCH /settings/masters/<master_type>/<id>/
DELETE /settings/masters/<master_type>/<id>/
```

**Auth:** IsAuthenticated + OrgSettings permission

**Master types:** `payment_method`, `plot_type`, `facing`, `source`, `status`, etc.

**POST Request Body:**
```json
{
  "code": "bank_transfer",
  "name": "Bank Transfer",
  "color": "#4CAF50",
  "description": "NEFT/RTGS/IMPS transfer",
  "is_active": true,
  "sort_order": 1
}
```

---

## 12. Bad Practices & Issues

### CRITICAL

| # | Issue | Location | Description |
|---|-------|----------|-------------|
| 1 | **Hardcoded SECRET_KEY** | `config/settings.py:39` | Django secret key is hardcoded in source. Must come from env. |
| 2 | **DEBUG=True in settings** | `config/settings.py:42` | Debug mode should be disabled in production. |
| 3 | **SQLite in production** | `config/settings.py:107-112` | SQLite is not suitable for production workloads. |
| 4 | **No rate limiting** | All auth endpoints | No throttling on login/forgot-password. Vulnerable to brute-force. |
| 5 | **`request._full_data` mutation** | `inventory/views.py:1057` | Mutates DRF private attribute — fragile and can break on upgrades. |
| 6 | **`__import__` inline** | `inventory/views.py:810` | Uses `__import__("django.db.models", fromlist=["Sum"])` instead of proper import. |
| 7 | **Bitwise `\|` vs union bug** | `inventory/phase5_services.py:55` | `or` binds tighter than `\|`, causing fallback to miss payment methods. |
| 8 | **No CSRF on function views** | All `@api_view` views | DRF function views may not handle CSRF correctly with session auth. |

### HIGH

| # | Issue | Location | Description |
|---|-------|----------|-------------|
| 9 | **No DRF serializers in leads** | `leads/serializers.py` | Uses hand-rolled dict functions instead of serializers. Loses validation, schema generation, `is_valid()`. |
| 10 | **Side-effects in validation** | `organizations/serializers.py:34` | `AddMembershipSerializer.validate_email` stores `self.user` as side-effect. Fragile pattern. |
| 11 | **No pagination on list endpoints** | Multiple views | `platform_organizations`, `roles`, `permissions`, `holidays`, `categories` return unbounded results. |
| 12 | **Duplicate helper functions** | `leads/views.py`, `inventory/views.py`, etc. | `_validation_response()`, `_paginate()` copy-pasted across 5+ modules. Should be centralized. |
| 13 | **Synchronous email sending** | `users/views.py:64` | `send_mail(..., fail_silently=False)` blocks request on email delivery. |
| 14 | **No file size/type validation** | `leads/views.py:290`, `documents/views.py` | File uploads accepted without size limits. DoS risk. |
| 15 | **`select_for_update` without timeout** | `employee_views.py:306`, `leads/views.py:654` | Potential deadlocks under contention. |
| 16 | **Raw IntegerFields for FKs** | `employee_serializers.py`, `documents/` | No queryset validation — invalid IDs cause 500 errors. |
| 17 | **No API versioning** | All endpoints | No `/v1/` prefix. Breaking changes will be difficult to manage. |
| 18 | **Custom pagination** | Multiple modules | Every module reimplements pagination. Should use DRF's `PageNumberPagination`. |

### MEDIUM

| # | Issue | Location | Description |
|---|-------|----------|-------------|
| 19 | **`RecentlyViewedPlot` side-effect on GET** | `inventory/views.py:684` | Writes to DB on GET request. GET should be idempotent. |
| 20 | **Missing `read_only_fields`** | `users/serializers.py` | `is_active`, `is_staff`, `is_superuser` are writable by default. |
| 21 | **N+1 query risk** | `users/serializers.py:16` | `get_organization_memberships` does per-user DB query. |
| 22 | **Inconsistent error responses** | All views | Some return `{detail: [...]}`, others `{field: [...]}`, others `{field: "msg"}`. |
| 23 | **Mixed HTTP status usage** | All views | Mix of `status.HTTP_200_OK` and raw `200`, `201`, `400`. |
| 24 | **`Payment` model has no choices** | `inventory/models.py` | `payment_method` is free-text CharField. `Payment.Method` choices exist but aren't used on the field. |
| 25 | **Dual role system** | `organizations/models.py` | `OrganizationMembership.role` (CharField) AND `organization_role` (FK) both exist. Legacy fallback in `has_permission()`. |
| 26 | **God Object: OrganizationMembership** | `organizations/models.py` | Contains HR data (`salary`, `dob`, `shift`, `photo`) alongside membership. Violates SRP. |
| 27 | **Immutability race condition** | Multiple models | `save()` override checks `exists()` — TOCTOU race. Should use `update()` or flag. |
| 28 | **`auto_now=True` on `viewed_at`** | `inventory/models.py` | Can't set explicit view time. Should use `default=timezone.now`. |
| 29 | **No soft deletes** | All models | Hard deletes on financial data (`Payment`, `PlotBooking`). Risk of data loss. |
| 30 | **No audit logging** | Lead delete, visit cancel, booking cancel | Many destructive operations have no audit trail. |
| 31 | **`hardcoded duration_minutes=1`** | `leads/views.py:598` | Every site visit logged as 1 minute duration. |
| 32 | **No `__str__` on models** | `FollowUpCall`, `PaymentRefund`, etc. | Makes admin/debug harder. |
| 33 | **Django internals access** | `inventory/serializers.py` | `_state.adding = False` — accessing Django internals. |
| 34 | **Multiple statements per line** | `documents/serializers.py`, `system_settings/serializers.py` | Poor readability and debuggability. |
| 35 | **No signals/post_save hooks** | All models | Status invariants only enforced in service code. Code bypass can violate invariants. |
| 36 | **`CommonMiddleware` duplicated** | `config/settings.py:75,81` | Listed twice in MIDDLEWARE. |
| 37 | **Encryption key in env** | `config/settings.py:164` | `INTEGRATION_ENCRYPTION_KEY` must never be in version control. |
| 38 | **Audit log IP tracking** | `system_settings/audit.py:14` | Only reads `REMOTE_ADDR`. Behind proxy, logs proxy IP. |
| 39 | **`PaymentReceipt` race condition** | `inventory/phase5_services.py:116` | `get_or_create` without `select_for_update`. |

---

*Documentation generated on 2026-08-30*
