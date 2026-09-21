from django.urls import path

from . import views

app_name = "expenses"

urlpatterns = [
    path("categories/", views.category_list, name="categories"),
    path("categories/<int:category_id>/", views.category_detail, name="category-detail"),
    path("reports/summary/", views.report_summary, name="report-summary"),
    path("reports/export/", views.report_export, name="report-export"),
    path("expenses/", views.expense_list, name="list"),
    path("expenses/history/", views.expense_history, name="history"),
    path("expenses/deleted/", views.deleted_expenses, name="deleted"),
    path("expenses/pending-approval/", views.pending_approval, name="pending-approval"),
    path("expenses/<int:expense_id>/", views.expense_detail, name="detail"),
    path("expenses/<int:expense_id>/cancel/", views.expense_cancel, name="cancel"),
    path("expenses/<int:expense_id>/approve/", views.expense_approve, name="approve"),
    path("expenses/<int:expense_id>/reject/", views.expense_reject, name="reject"),
    path("expenses/<int:expense_id>/request-changes/", views.expense_request_changes, name="request-changes"),
    path("payments/unpaid/", views.unpaid_payments, name="payments-unpaid"),
    path("payments/paid/", views.paid_payments, name="payments-paid"),
    path("expenses/<int:expense_id>/mark-paid/", views.expense_mark_paid, name="mark-paid"),
    path("reimbursements/", views.reimbursement_list, name="reimbursements"),
    path("reimbursements/<int:reimbursement_id>/adjust-advance/", views.reimbursement_adjust_advance, name="reimbursement-adjust-advance"),
    path("reimbursements/<int:reimbursement_id>/approve/", views.reimbursement_approve, name="reimbursement-approve"),
    path("reimbursements/<int:reimbursement_id>/reject/", views.reimbursement_reject, name="reimbursement-reject"),
]
