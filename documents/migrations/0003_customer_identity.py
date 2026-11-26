from collections import defaultdict

from django.db import migrations, models
import django.db.models.deletion


def _lead_name(lead):
    return " ".join(
        part.strip()
        for part in (getattr(lead, "first_name", ""), getattr(lead, "last_name", ""))
        if part and part.strip()
    )


def _row_order(row):
    return (row.get("uploaded_at") is None, row.get("uploaded_at"), row["pk"])


def _document_rewrite_plan(rows, customer_by_reference):
    groups = defaultdict(list)
    for row in rows:
        customer_id = customer_by_reference[(row["customer_id"], row["organization_id"])]
        key = (row["organization_id"], customer_id, row["document_category_id"])
        groups[key].append(row)

    plan = []
    for (_, customer_id, _), group in groups.items():
        ordered = sorted(group, key=_row_order)
        active_rows = [row for row in ordered if row["is_active"]]
        active_pk = max(active_rows, key=_row_order)["pk"] if active_rows else None
        for version, row in enumerate(ordered, start=1):
            plan.append((row["pk"], customer_id, version, row["pk"] == active_pk))
    return plan


def _requirement_rewrite_plan(rows, customer_by_reference):
    groups = defaultdict(list)
    for row in rows:
        customer_id = customer_by_reference[(row["customer_id"], row["organization_id"])]
        key = (row["organization_id"], customer_id, row["document_category_id"])
        groups[key].append(row)

    plan = []
    for (_, customer_id, _), group in groups.items():
        ordered = sorted(group, key=lambda row: (row.get("created_at") is None, row.get("created_at"), row["pk"]))
        keep = ordered[-1]
        duplicate_ids = [row["pk"] for row in ordered[:-1]]
        plan.append((
            keep["pk"],
            customer_id,
            any(row["is_mandatory"] for row in ordered),
            any(row["is_active"] for row in ordered),
            duplicate_ids,
        ))
    return plan


def _customer_for_lead(apps, lead, organization_id):
    Customer = apps.get_model("inventory", "Customer")
    Project = apps.get_model("inventory", "Project")
    customer = Customer.objects.filter(
        organization_id=organization_id,
        project_id=lead.project_id,
        lead_id=lead.pk,
    ).first()
    if customer:
        return customer

    project = Project.objects.get(pk=lead.project_id)
    code = f"{project.code}-DOC-{lead.pk}"
    suffix = 1
    while Customer.objects.filter(project_id=project.pk, customer_code=code).exists():
        suffix += 1
        code = f"{project.code}-DOC-{lead.pk}-{suffix}"
    phone = lead.phone or ""
    email = lead.email or ""
    if phone and Customer.objects.filter(project_id=project.pk, phone=phone).exists():
        phone = ""
    if email and Customer.objects.filter(project_id=project.pk, email__iexact=email).exists():
        email = ""
    return Customer.objects.create(
        organization_id=organization_id,
        project_id=project.pk,
        lead_id=lead.pk,
        customer_code=code,
        full_name=_lead_name(lead),
        phone=phone,
        email=email,
        address=lead.address or "",
    )


def migrate_customer_references(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    CustomerDocument = apps.get_model("documents", "CustomerDocument")
    CustomerDocumentRequirement = apps.get_model("documents", "CustomerDocumentRequirement")
    document_rows = list(CustomerDocument.objects.values(
        "pk", "customer_id", "organization_id", "document_category_id", "uploaded_at", "is_active"
    ))
    requirement_rows = list(CustomerDocumentRequirement.objects.values(
        "pk", "customer_id", "organization_id", "document_category_id", "created_at", "is_mandatory", "is_active"
    ))
    lead_ids = {row["customer_id"] for row in document_rows}
    lead_ids.update(row["customer_id"] for row in requirement_rows)
    customers = {}
    for lead in Lead.objects.filter(pk__in=lead_ids).iterator():
        organizations = {
            row["organization_id"] for row in document_rows if row["customer_id"] == lead.pk
        }
        organizations.update(
            row["organization_id"] for row in requirement_rows if row["customer_id"] == lead.pk
        )
        for organization_id in organizations:
            customers[(lead.pk, organization_id)] = _customer_for_lead(apps, lead, organization_id)

    customer_by_reference = {key: customer.pk for key, customer in customers.items()}

    # The old schema points at Lead and has uniqueness constraints on the old IDs.
    # Stage references in a disjoint namespace before assigning Customer IDs so both
    # the FK transition and customer/category collisions are safe on SQLite/Postgres.
    for row in document_rows:
        CustomerDocument.objects.filter(pk=row["pk"]).update(customer_id=-row["pk"])
    for row in requirement_rows:
        CustomerDocumentRequirement.objects.filter(pk=row["pk"]).update(customer_id=-row["pk"])

    for document_id, customer_id, version, is_active in _document_rewrite_plan(document_rows, customer_by_reference):
        CustomerDocument.objects.filter(pk=document_id).update(
            customer_id=customer_id,
            version=version,
            is_active=is_active,
        )
    for requirement_id, customer_id, is_mandatory, is_active, duplicate_ids in _requirement_rewrite_plan(requirement_rows, customer_by_reference):
        CustomerDocumentRequirement.objects.filter(pk=requirement_id).update(
            customer_id=customer_id,
            is_mandatory=is_mandatory,
            is_active=is_active,
        )
        if duplicate_ids:
            CustomerDocumentRequirement.objects.filter(pk__in=duplicate_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_employee_phase2"),
        ("inventory", "0021_backfill_booking_customers"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customerdocument",
            name="customer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="documents",
                to="inventory.customer",
                db_constraint=False,
            ),
        ),
        migrations.AlterField(
            model_name="customerdocumentrequirement",
            name="customer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="document_requirements",
                to="inventory.customer",
                db_constraint=False,
            ),
        ),
        migrations.RunPython(migrate_customer_references, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="customerdocument",
            name="customer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="documents",
                to="inventory.customer",
            ),
        ),
        migrations.AlterField(
            model_name="customerdocumentrequirement",
            name="customer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="document_requirements",
                to="inventory.customer",
            ),
        ),
    ]
