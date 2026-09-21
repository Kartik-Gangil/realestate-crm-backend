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
from organizations.health import healthz, readyz
from config.metrics import metrics

urlpatterns = [
    path('healthz', healthz, name='healthz'),
    path('readyz', readyz, name='readyz'),
    path('metrics', metrics, name='metrics'),
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.urls')),
    # Versioned aliases are provided for new clients; legacy routes remain supported.
    path('api/v1/auth/', include(('users.urls', 'users_v1'), namespace='users_v1')),
    path('api/', include('organizations.urls')),
    path('api/', include('expenses.urls')),
    path('api/v1/', include('organizations.urls')),
    path('api/v1/', include(('expenses.urls', 'expenses_v1'), namespace='expenses_v1')),
    path('api/settings/', include('system_settings.urls')),
    path('api/v1/settings/', include('system_settings.urls')),
    path('api/organizations/<slug:organization_slug>/', include('system_settings.organization_urls')),
    path('api/v1/organizations/<slug:organization_slug>/', include('system_settings.organization_urls')),
    path('api/organizations/<slug:organization_slug>/', include('leads.urls')),
    path('api/v1/organizations/<slug:organization_slug>/', include(('leads.urls', 'leads_v1'), namespace='leads_v1')),
    path('api/organizations/<slug:organization_slug>/', include('customers.urls')),
    path('api/v1/organizations/<slug:organization_slug>/', include(('customers.urls', 'customers_v1'), namespace='customers_v1')),
    path('api/organizations/<slug:organization_slug>/', include('inventory.urls')),
    path('api/v1/organizations/<slug:organization_slug>/', include(('inventory.urls', 'inventory_v1'), namespace='inventory_v1')),
    path('api/organizations/<slug:organization_slug>/', include('documents.urls')),
    path('api/v1/organizations/<slug:organization_slug>/', include(('documents.urls', 'documents_v1'), namespace='documents_v1')),
]
