from django.urls import path

from . import views

app_name = "leads"

urlpatterns = [
    path("leads/", views.lead_list, name="list"),
    path("leads/check-duplicate/", views.check_duplicate_lead, name="check-duplicate"),
    path("leads/manual/", views.manual_lead_create, name="manual-create"),
    path("leads/merge/", views.merge_leads, name="merge-leads"),
    path("leads/webhooks/meta/", views.meta_webhook, name="meta-webhook"),
    path("leads/webhooks/google/", views.google_webhook, name="google-webhook"),
    path("leads/sync/<str:connector>/", views.sync_connector, name="sync-connector"),
    path("leads/import/", views.import_leads_csv, name="import-csv"),
    path("leads/import-csv/", views.import_leads_csv, name="import-csv-v1"),
    path("leads/import-batches/<int:batch_id>/", views.import_batch_progress, name="import-batch-progress"),
    path("leads/import-batches/<int:batch_id>/error-report/", views.import_batch_error_report, name="import-batch-error-report"),
    path("leads/assigned/", views.assigned_leads, name="assigned-leads"),
    path("leads/bulk_reset/", views.remove_assignment_of_lead, name="reset-assigned-leads"),
    path("leads/assign-round-robin/", views.assign_leads_round_robin_view, name="assign-round-robin"),
    path("leads/<int:lead_id>/assign/", views.assign_lead, name="assign-lead"),
    path("leads/<int:lead_id>/status/", views.transition_lead_status, name="transition-status"),
    path("leads/bulk-action/", views.bulk_lead_action, name="bulk-action"),
    path("leads/dashboard/", views.lead_dashboard, name="dashboard"),
    path("leads/summary/", views.lead_summary, name="summary"),
    path("leads/<int:lead_id>/", views.lead_detail, name="detail"),
    path("leads/<int:lead_id>/follow-ups/", views.follow_up_list, name="follow-up-list"),
    path("dashboard/", views.lead_dashboard, name="organization-dashboard"),
    path("summary/", views.lead_summary, name="organization-summary"),
    path("sitevisits/", views.sitevisit_dashboard, name="site-visit"),
    path("sitevisits/upcoming/", views.sitevisit_upcoming, name="site-visit-upcoming"),
    path("sitevisits/today/", views.sitevisit_today, name="site-visit-today"),
    path("sitevisits/calendar/", views.sitevisit_calendar, name="site-visit-calendar"),
    path("sitevisits/analytics/", views.sitevisit_analytics, name="site-visit-analytics"),
    path("sitevisits/<int:site_visit_id>/", views.sitevisit_detail, name="site-visit-detail"),
    path("sitevisits/<int:site_visit_id>/reschedule/", views.sitevisit_reschedule, name="site-visit-reschedule"),
    path("sitevisits/<int:site_visit_id>/history/", views.sitevisit_history, name="site-visit-history"),
    path("sitevisits/<int:site_visit_id>/cancel/", views.sitevisit_cancel, name="site-visit-cancel"),
    path("sitevisits/<int:site_visit_id>/no-show/", views.sitevisit_no_show, name="site-visit-no-show"),
    path("sitevisits/<int:site_visit_id>/outcome/", views.sitevisit_outcome, name="site-visit-outcome"),
    path("leads/<int:lead_id>/sitevisits/", views.lead_sitevisits, name="lead-site-visits"),
    # Kept for compatibility with the existing frontend.
    path("reschedulevisit/", views.rescheduledSitevisit, name="reschedule-site-visit"),
]
