from django.urls import path
from . import views

app_name = "documents"
urlpatterns = [
    path("documents/", views.document_list, name="list"), 
    path("documents/categories/", views.categories, name="categories"), 
    path("documents/categories/<int:category_id>/", views.category_detail, name="category-detail"),
    path("documents/pending-verification/", views.pending_verification, name="pending"), 
    path("documents/expiry-alerts/", views.expiry_alerts, name="expiry-alerts"),
    path("documents/<int:document_id>/", views.document_detail, name="detail"), 
    path("documents/<int:document_id>/download/", views.document_download, name="download"), 
    path("documents/<int:document_id>/history/", views.document_history, name="history"),
    path("documents/<int:document_id>/under-verification/", views.document_under_verification, name="under-verification"), 
    path("documents/<int:document_id>/verify/", views.document_verify, name="verify"), 
    path("documents/<int:document_id>/reject/", views.document_reject, name="reject"), 
    path("documents/<int:document_id>/archive/", views.document_archive, name="archive"),
    path("customers/<int:customer_id>/documents/", views.customer_documents, name="customer-documents"), 
    path("customers/<int:customer_id>/document-requirements/", views.requirements, name="requirements"), 
    path("customers/<int:customer_id>/document-requirements/<int:requirement_id>/", views.requirement_detail, name="requirement-detail"),
    path("employees/<int:employee_id>/documents/", views.employee_documents, name="employee-documents"),
    path("employee-documents/<int:document_id>/", views.employee_document_detail, name="employee-document-detail"),
    path("employee-documents/<int:document_id>/download/", views.employee_document_download, name="employee-document-download"),
    path("employee-documents/<int:document_id>/history/", views.employee_document_history, name="employee-document-history"),
    path("employee-documents/<int:document_id>/archive/", views.employee_document_archive, name="employee-document-archive"),
]
