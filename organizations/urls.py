from django.urls import path

from . import views

urlpatterns = [
    path("platform/admins/", views.platform_admins, name="platform-admins"),
    path("platform/organizations/", views.platform_organizations, name="platform-organizations"),
    path("platform/organizations/<slug:slug>/access/", views.platform_organization_access, name="platform-organization-access"),
    path("organizations/<slug:slug>/members/", views.organization_members, name="organization-members"),
    path("organizations/<slug:slug>/members/<int:membership_id>/tab-permissions/", views.member_tab_permissions, name="member-tab-permissions"),
    path("organizations/<slug:slug>/my-tab-permissions/", views.my_tab_permissions, name="my-tab-permissions"),
]