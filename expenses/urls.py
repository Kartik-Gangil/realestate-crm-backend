from django.urls import path

from . import views

urlpatterns = [
    path("reports/summary/", views.report_summary, name="expense-report-summary"),
    path("reports/export/", views.report_export, name="expense-report-export"),
    path("payments/unpaid/", views.unpaid_payments, name="expense-payments-unpaid"),
    path("payments/paid/", views.paid_payments, name="expense-payments-paid"),
    path("reimbursements/", views.reimbursement_list, name="expense-reimbursements"),
    path("reimbursements/<int:reimbursement_id>/adjust-advance/", views.reimbursement_adjust_advance, name="expense-reimbursement-adjust-advance"),
    path("reimbursements/<int:reimbursement_id>/approve/", views.reimbursement_approve, name="expense-reimbursement-approve"),
    path("reimbursements/<int:reimbursement_id>/reject/", views.reimbursement_reject, name="expense-reimbursement-reject"),
    path("expenses/", views.expense_list, name="expense-list"),
    path("expenses/history/", views.expense_history, name="expense-history"),
    path("expenses/deleted/", views.deleted_expenses, name="expense-deleted"),
    path("expenses/pending-approval/", views.pending_approval, name="expense-pending-approval"),
    path("expenses/<int:expense_id>/", views.expense_detail, name="expense-detail"),
    path("expenses/<int:expense_id>/cancel/", views.expense_cancel, name="expense-cancel"),
    path("expenses/<int:expense_id>/approve/", views.expense_approve, name="expense-approve"),
    path("expenses/<int:expense_id>/reject/", views.expense_reject, name="expense-reject"),
    path("expenses/<int:expense_id>/request-changes/", views.expense_request_changes, name="expense-request-changes"),
    path("expenses/<int:expense_id>/mark-paid/", views.expense_mark_paid, name="expense-mark-paid"),
    path("expenses/<int:expense_id>/reimburse/", views.expense_reimburse, name="expense-reimburse"),
    path("expenses/<int:expense_id>/receipt/", views.expense_receipt, name="expense-receipt"),
    path("categories/", views.category_list, name="expense-category-list"),
    path("categories/<int:category_id>/", views.category_detail, name="expense-category-detail"),
]
