from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0004_project_scoped_constraints")]

    operations = [
        migrations.AddConstraint(
            model_name="customerdocument",
            constraint=models.UniqueConstraint(fields=("organization", "customer", "document_category", "version"), condition=models.Q(project__isnull=True), name="documents_version_legacy"),
        ),
        migrations.AddConstraint(
            model_name="customerdocument",
            constraint=models.UniqueConstraint(fields=("organization", "customer", "document_category"), condition=models.Q(project__isnull=True, is_active=True), name="documents_one_active_legacy"),
        ),
        migrations.AddConstraint(
            model_name="customerdocumentrequirement",
            constraint=models.UniqueConstraint(fields=("organization", "customer", "document_category"), condition=models.Q(project__isnull=True), name="documents_requirement_legacy"),
        ),
        migrations.AddConstraint(
            model_name="documentcategory",
            constraint=models.UniqueConstraint(fields=("organization", "code"), condition=models.Q(project__isnull=True), name="documents_category_org_code_legacy"),
        ),
        migrations.AddConstraint(
            model_name="employeedocument",
            constraint=models.UniqueConstraint(fields=("organization", "employee", "document_category", "version"), condition=models.Q(project__isnull=True), name="employee_document_version_legacy"),
        ),
        migrations.AddConstraint(
            model_name="employeedocument",
            constraint=models.UniqueConstraint(fields=("organization", "employee", "document_category"), condition=models.Q(project__isnull=True, is_active=True), name="employee_document_one_active_legacy"),
        ),
        migrations.AddConstraint(
            model_name="employeedocumentcategory",
            constraint=models.UniqueConstraint(fields=("organization", "code"), condition=models.Q(project__isnull=True), name="employee_document_category_legacy"),
        ),
    ]
