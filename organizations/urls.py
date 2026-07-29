from django.urls import path

from . import views

urlpatterns = [
    path("platform/admins/", views.platform_admins, name="platform-admins"),
    path("platform/organizations/", views.platform_organizations, name="platform-organizations"),
    path("platform/organizations/<slug:slug>/access/", views.platform_organization_access, name="platform-organization-access"),
    path("organizations/<slug:slug>/members/", views.organization_members, name="organization-members"),
]