from django.urls import path

from . import views

urlpatterns = [
    path("expenses/", views.expense_list, name="expense-list"),
    path("expenses/<int:expense_id>/receipt/", views.expense_receipt, name="expense-receipt"),
    path("categories/", views.category_list, name="expense-category-list"),
    path("categories/<int:category_id>/", views.category_detail, name="expense-category-detail"),
]
