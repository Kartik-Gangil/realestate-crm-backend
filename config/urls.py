"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from system_settings import views as system_settings_views
from core.metrics_views import metrics

from .health import healthz, readyz

urlpatterns = [
    path('healthz', healthz, name='healthz'),
    path('readyz', readyz, name='readyz'),
    path('metrics', metrics, name='metrics'),
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.urls')),
    path('api/v1/auth/', include(('users.urls', 'users-v1'), namespace='users-v1')),
    path('api/v1/audit-logs/', system_settings_views.audit_logs, name='v1-audit-logs'),
    path('api/', include('organizations.urls')),
    path('api/', include('expenses.urls')),
    path('api/settings/', include('system_settings.urls')),
    path('api/organizations/<slug:organization_slug>/', include('system_settings.organization_urls')),
    path('api/organizations/<slug:organization_slug>/', include('leads.urls')),
    path('api/organizations/<slug:organization_slug>/', include('inventory.urls')),
    path('api/organizations/<slug:organization_slug>/', include('documents.urls')),
    path('api/v1/', include(('organizations.urls', 'organizations-v1'), namespace='organizations-v1')),
    path('api/v1/', include(('expenses.urls', 'expenses-v1'), namespace='expenses-v1')),
    path('api/v1/settings/', include(('system_settings.urls', 'system-settings-platform-v1'), namespace='system-settings-platform-v1')),
    path('api/v1/organizations/<slug:organization_slug>/', include(('system_settings.organization_urls', 'system-settings-v1'), namespace='system-settings-v1')),
    path('api/v1/organizations/<slug:organization_slug>/', include(('leads.urls', 'leads-v1'), namespace='leads-v1')),
    path('api/v1/organizations/<slug:organization_slug>/', include('leads.telecalling_urls')),
    path('api/v1/organizations/<slug:organization_slug>/', include(('inventory.urls', 'inventory-v1'), namespace='inventory-v1')),
    path('api/v1/organizations/<slug:organization_slug>/', include(('documents.urls', 'documents-v1'), namespace='documents-v1')),
]

