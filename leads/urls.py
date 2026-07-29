from django.urls import path

from . import views

app_name = "leads"

urlpatterns = [
    path("leads/", views.lead_list, name="list"),
    path("leads/dashboard/", views.lead_dashboard, name="dashboard"),
    path("leads/summary/", views.lead_summary, name="summary"),
    path("leads/<int:lead_id>/", views.lead_detail, name="detail"),
    path("leads/<int:lead_id>/follow-ups/", views.follow_up_list, name="follow-up-list"),
    path("dashboard/", views.lead_dashboard, name="organization-dashboard"),
    path("summary/", views.lead_summary, name="organization-summary"),
]