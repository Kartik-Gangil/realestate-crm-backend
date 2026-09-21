import io
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone


def generate_agreement_pdf(*, agreement):
    from xhtml2pdf import pisa

    booking = agreement.booking
    plot = booking.plot
    lead = booking.lead

    context = {
        "organization_name": booking.organization.name,
        "agreement_number": agreement.agreement_number or f"AGR-{agreement.id}",
        "agreement_date": (agreement.agreement_date or date.today()).strftime("%d %B %Y"),
        "buyer_name": lead.full_name,
        "buyer_phone": lead.phone,
        "buyer_email": lead.email or "",
        "plot_number": plot.plot_number,
        "block_name": plot.block.name,
        "plot_size": str(plot.size),
        "plot_type": plot.get_plot_type_display(),
        "sale_amount": str(booking.final_price or plot.total_price or "0.00"),
        "deposit_amount": "0.00",
        "deposit_date": "N/A",
        "balance_amount": str(booking.final_price or plot.total_price or "0.00"),
        "registration_timeline": "30",
        "notes": agreement.notes or "",
        "generated_at": timezone.now().strftime("%d %B %Y at %I:%M %p"),
    }

    html_string = render_to_string("agreements/agreement_template.html", context)
    result = io.BytesIO()
    pdf_status = pisa.CreatePDF(io.BytesIO(html_string.encode("utf-8")), dest=result, encoding="utf-8")

    if pdf_status.err:
        raise ValidationError({"pdf": "Failed to generate agreement PDF."})

    filename = f"agreement_{agreement.id}_{timezone.now():%Y%m%d}.pdf"
    agreement.generated_pdf.save(filename, result, save=True)
    return agreement


def upload_signed_agreement(*, agreement, uploaded_file, user):
    from documents.services import _validate_file

    _validate_file(uploaded_file)
    with transaction.atomic():
        agr = type(agreement).objects.select_for_update().get(pk=agreement.pk)
        if agr.status == agr.Status.SIGNED and agr.signed_file:
            raise ValidationError({"agreement": "Agreement is already signed with a file."})
        filename = f"signed_{agr.id}_{timezone.now():%Y%m%d}.pdf"
        agr.signed_file.save(filename, uploaded_file, save=False)
        agr.signed_file_name = uploaded_file.name
        agr.signed_file_size = uploaded_file.size
        agr.status = agr.Status.SIGNED
        agr.save(update_fields=["signed_file", "signed_file_name", "signed_file_size", "status", "updated_at"])
        return agr


def download_agreement_pdf(*, agreement):
    if not agreement.generated_pdf:
        raise ValidationError({"agreement": "No generated PDF available. Generate one first."})
    return agreement.generated_pdf


def download_signed_agreement(*, agreement):
    if not agreement.signed_file:
        raise ValidationError({"agreement": "No signed agreement available."})
    return agreement.signed_file
