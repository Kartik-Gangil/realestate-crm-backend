from django.urls import path

from . import views

app_name = "leads"

urlpatterns = [
    path("telecalling/queue/", views.telecalling_queue, name="telecalling-queue"),
    path("telecalling/analytics/", views.telecalling_analytics, name="telecalling-analytics"),
    path("telecalling/queue/redistribute/", views.telecalling_redistribute, name="telecalling-redistribute"),
    path("telecalling/dispositions/", views.telecalling_dispositions, name="telecalling-dispositions"),
    path("telecalling/calls/log/", views.telecalling_call_log, name="telecalling-call-log"),
    path("telecalling/follow-ups/", views.telecalling_follow_ups, name="telecalling-follow-ups"),
    path("leads/", views.lead_list, name="list"),
    path("leads/import/", views.import_leads_csv, name="import-csv"),
    path("leads/import-csv/", views.import_leads_csv, name="phase4-import-csv"),
    path("leads/import-csv/<int:batch_id>/", views.lead_import_batch_detail, name="lead-import-batch-detail"),
    path("leads/manual/", views.manual_lead, name="manual-lead"),
    path("leads/check-duplicate/", views.check_duplicate, name="check-duplicate"),
    path("leads/merge/", views.merge_lead, name="merge-lead"),
    path("leads/bulk-action/", views.bulk_action, name="bulk-action"),
    path("leads/sync/meta/", views.sync_meta, name="sync-meta"),
    path("leads/sync/google/", views.sync_google, name="sync-google"),
    path("leads/assigned/", views.assigned_leads, name="assigned-leads"),
    path("leads/bulk_reset/", views.remove_assignment_of_lead, name="reset-assigned-leads"),
    path("leads/assign-round-robin/", views.assign_leads_round_robin_view, name="assign-round-robin"),
    path("leads/<int:lead_id>/assign/", views.assign_lead, name="assign-lead"),
    path("leads/<int:lead_id>/status/", views.lead_status, name="lead-status"),
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
