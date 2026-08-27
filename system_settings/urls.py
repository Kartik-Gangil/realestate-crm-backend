from django.urls import path
from . import views

urlpatterns = [
    path("overview/", views.overview), path("organizations/", views.organizations), 
    path("system-info/", views.system_info),
    path("audit-logs/", views.audit_logs),
    path("backups/", views.backups), path("maintenance/", views.maintenance), path("health-check/", views.health),
]
