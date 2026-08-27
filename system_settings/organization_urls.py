from django.urls import path
from . import views

urlpatterns = [
    path("settings/general/", views.general_settings),
    path("settings/integrations/", views.integrations),
    path("settings/integrations/<int:integration_id>/", views.integration_detail),
    path("settings/system-parameters/", views.system_parameters),
    path("settings/system-parameters/<int:parameter_id>/", views.system_parameter_detail),
    path("settings/masters/", views.masters), path("settings/masters/<slug:master_type>/", views.masters), path("settings/masters/<slug:master_type>/<int:item_id>/", views.master_detail),
    path("permissions/", views.permissions), path("role-mapping/", views.role_mapping), path("role-mapping/<int:membership_id>/", views.role_mapping_detail), path("access-matrix/", views.access_matrix),
]
