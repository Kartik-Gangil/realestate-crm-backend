from django.db import migrations


def _lead_name(lead):
    return " ".join(
        part.strip()
        for part in (getattr(lead, "first_name", ""), getattr(lead, "last_name", ""))
        if part and part.strip()
    )


def backfill_booking_customers(apps, schema_editor):
    Customer = apps.get_model("inventory", "Customer")
    CustomerCodeSequence = apps.get_model("inventory", "CustomerCodeSequence")
    PlotBooking = apps.get_model("inventory", "PlotBooking")

    for booking in PlotBooking.objects.filter(customer_id__isnull=True).select_related("lead", "plot__project").iterator():
        lead = booking.lead
        project = booking.plot.project
        customer = Customer.objects.filter(
            organization_id=booking.organization_id,
            project_id=project.pk,
            lead_id=lead.pk,
        ).first()
        if customer is None:
            sequence, _ = CustomerCodeSequence.objects.get_or_create(project_id=project.pk, defaults={"next_number": 1})
            number = sequence.next_number
            sequence.next_number += 1
            sequence.save(update_fields=["next_number"])
            phone = lead.phone or ""
            email = lead.email or ""
            if phone and Customer.objects.filter(project_id=project.pk, phone=phone).exists():
                phone = ""
            if email and Customer.objects.filter(project_id=project.pk, email__iexact=email).exists():
                email = ""
            customer = Customer.objects.create(
                organization_id=booking.organization_id,
                project_id=project.pk,
                lead_id=lead.pk,
                customer_code=f"{project.code}-C-{number:06d}",
                full_name=_lead_name(lead),
                phone=phone,
                email=email,
                address=lead.address or "",
            )
        PlotBooking.objects.filter(pk=booking.pk).update(project_id=project.pk, customer_id=customer.pk)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0020_customer_identity_constraints")]
    operations = [migrations.RunPython(backfill_booking_customers, migrations.RunPython.noop)]
