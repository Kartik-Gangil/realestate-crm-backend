from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("customers/", views.customer_list, name="customer-list"),
    path("customers/<int:customer_id>/", views.customer_detail, name="customer-detail"),
    path("customers/<int:customer_id>/360/", views.customer_360, name="customer-360"),
    path("customers/<int:customer_id>/notes/", views.customer_notes, name="customer-notes"),
]
