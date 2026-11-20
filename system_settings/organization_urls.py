from django.urls import path
from . import views

urlpatterns = [
    path("master-data/categories/", views.master_data_categories),
    path("master-data/", views.master_data_create),
    path("master-data/defaults/categories/", views.master_data_categories),
    path("master-data/defaults/", views.master_data_defaults_list),
    path("master-data/defaults/<int:item_id>/", views.master_data_defaults_update),
    path("master-data/defaults/<slug:category_code>/", views.master_data_defaults_list),
    path("master-data/<slug:category_code>/", views.master_data_list),
    path("master-data/<slug:category_code>/<int:item_id>/", views.master_data_update),
    path("system-parameters/", views.canonical_system_parameters),
    path("system-parameters/defaults/", views.canonical_system_parameter_defaults),
    path("settings/overview/", views.organization_overview),
    path("audit-logs/", views.organization_audit_logs),
    path("settings/general/", views.general_settings),
    path("settings/general/logo/", views.general_settings_logo),
    path("settings/integrations/", views.integrations),
    path("settings/integrations/<int:integration_id>/", views.integration_detail),
    path("settings/system-parameters/", views.system_parameters),
    path("settings/system-parameters/<int:parameter_id>/", views.system_parameter_detail),
    path("settings/masters/", views.masters), path("settings/masters/<slug:master_type>/", views.masters), path("settings/masters/<slug:master_type>/<int:item_id>/", views.master_detail),
    path("permissions/", views.permissions), path("role-mapping/", views.role_mapping), path("role-mapping/<int:membership_id>/", views.role_mapping_detail), path("access-matrix/", views.access_matrix),
]
