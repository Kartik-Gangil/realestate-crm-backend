"""Phase 3 audit coverage registry.

The registry is deliberately explicit so a newly introduced model cannot be
silently omitted from automatic audit logging.
"""

AUDIT_MODEL_LABELS = {
    "auth.User", "users.UserSecurityProfile", "users.DeveloperAccount",
    "organizations.Organization", "organizations.OrganizationMembership",
    "organizations.Department", "organizations.Permission",
    "organizations.OrganizationRole", "organizations.ProjectAssignment",
    "organizations.OrganizationHoliday", "organizations.AttendanceRecord",
    "organizations.LeaveRequest", "organizations.LeaveBalance",
    "organizations.PlatformOrganizationAccess",
    "system_settings.OrganizationSettings", "system_settings.MasterDataCategory",
    "system_settings.MasterData", "system_settings.IntegrationConfiguration",
    "system_settings.SystemParameter", "system_settings.BackupRecord",
    "leads.Lead", "leads.LeadCodeSequence", "leads.LeadHistory", "leads.LeadImportBatch",
    "leads.Sitevisit", "leads.SitevisitReschedule", "leads.FollowUpCall",
    "leads.LeadAssignmentHistory", "leads.LeadStatusHistory", "leads.LeadTag",
    "inventory.Project", "inventory.Block", "inventory.Plot", "inventory.PlotHold",
    "inventory.PlotBooking", "inventory.Customer", "inventory.CustomerNote", "inventory.CustomerCodeSequence",
    "inventory.BookingReceiptSequence", "inventory.BookingIdempotencyKey",
    "inventory.Payment", "inventory.PaymentRefund",
    "inventory.PaymentAllocation", "inventory.PaymentAdvance", "inventory.PaymentReceipt",
    "inventory.PaymentAdjustment", "inventory.Installment", "inventory.InstallmentPayment",
    "inventory.Agreement", "inventory.AgreementSignedDocument", "inventory.Registry",
    "inventory.RegistryDocument", "inventory.RegistryCharge", "inventory.Possession",
    "documents.DocumentCategory", "documents.CustomerDocumentRequirement",
    "documents.CustomerDocument", "documents.EmployeeDocumentCategory",
    "documents.EmployeeDocument", "expenses.ExpenseCategory", "expenses.Expense",
    "expenses.ApprovalStep", "expenses.Payment", "expenses.ReimbursementRequest",
}

EXCLUDED_MODEL_LABELS = {
    "core.TaskRecord", "core.Notification", "users.UserSession",
    "organizations.OrganizationActivity", "expenses.ActivityLog",
    "organizations.PerformanceReview",
    "system_settings.AuditLog", "documents.CustomerDocumentVerificationHistory",
    "inventory.PlotStatusHistory", "inventory.PaymentStatusHistory",
    "inventory.RegistryStatusHistory", "inventory.PlotSelection",
    "inventory.RecentlyViewedPlot",
}
