from django.db import migrations, models
import django.db.models.deletion


def _lead_name(lead):
    return " ".join(
        part.strip()
        for part in (getattr(lead, "first_name", ""), getattr(lead, "last_name", ""))
        if part and part.strip()
    )


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
    lead_ids = set(CustomerDocument.objects.values_list("customer_id", flat=True))
    lead_ids.update(CustomerDocumentRequirement.objects.values_list("customer_id", flat=True))
    customers = {}
    for lead in Lead.objects.filter(pk__in=lead_ids).iterator():
        organizations = set(CustomerDocument.objects.filter(customer_id=lead.pk).values_list("organization_id", flat=True))
        organizations.update(CustomerDocumentRequirement.objects.filter(customer_id=lead.pk).values_list("organization_id", flat=True))
        for organization_id in organizations:
            customers[(lead.pk, organization_id)] = _customer_for_lead(apps, lead, organization_id)

    for document in CustomerDocument.objects.all().iterator():
        customer = customers[(document.customer_id, document.organization_id)]
        CustomerDocument.objects.filter(pk=document.pk).update(customer_id=customer.pk)
    for requirement in CustomerDocumentRequirement.objects.all().iterator():
        customer = customers[(requirement.customer_id, requirement.organization_id)]
        CustomerDocumentRequirement.objects.filter(pk=requirement.pk).update(customer_id=customer.pk)


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_employee_phase2"),
        ("inventory", "0021_backfill_booking_customers"),
    ]

    operations = [
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
