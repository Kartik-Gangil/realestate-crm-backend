from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0003_customerdocument_project_and_more")]

    operations = [
        migrations.RemoveConstraint(model_name=model_name, name=constraint_name)
        for model_name, constraint_name in (
            ("customerdocument", "documents_version_unique"),
            ("customerdocument", "documents_one_active_version"),
            ("customerdocumentrequirement", "documents_requirement_unique"),
            ("documentcategory", "documents_category_org_code_unique"),
            ("employeedocument", "employee_document_version_unique"),
            ("employeedocument", "employee_document_one_active"),
            ("employeedocumentcategory", "employee_document_category_unique"),
        )
    ] + [
        migrations.AddConstraint(
            model_name="customerdocument",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "customer", "document_category", "version"),
                name="documents_version_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="customerdocument",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "customer", "document_category"),
                condition=models.Q(is_active=True),
                name="documents_one_active_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="customerdocumentrequirement",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "customer", "document_category"),
                name="documents_requirement_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="documentcategory",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "code"),
                name="documents_category_org_code_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeedocument",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "employee", "document_category", "version"),
                name="employee_document_version_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeedocument",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "employee", "document_category"),
                condition=models.Q(is_active=True),
                name="employee_document_one_active",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeedocumentcategory",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "code"),
                name="employee_document_category_unique",
            ),
        ),
    ]
