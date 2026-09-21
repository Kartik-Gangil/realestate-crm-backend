import io

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

from .models import BookingReceipt, PlotBooking


def get_or_create_booking_receipt(*, booking):
    with transaction.atomic():
        locked_booking = PlotBooking.objects.select_for_update().select_related(
            "organization", "lead", "plot", "plot__block"
        ).get(pk=booking.pk)
        receipt = BookingReceipt.objects.filter(booking=locked_booking).first()
        if receipt:
            return receipt
        organization = locked_booking.organization.__class__.objects.select_for_update().get(
            pk=locked_booking.organization_id
        )
        last = BookingReceipt.objects.filter(organization=organization).order_by("-sequence").first()
        sequence = (last.sequence if last else 0) + 1
        receipt = BookingReceipt.objects.create(
            organization=organization,
            project=locked_booking.project,
            booking=locked_booking,
            sequence=sequence,
            receipt_number=f"RCP-{sequence:06d}",
        )
        return receipt


def booking_receipt_pdf(*, booking):
    from xhtml2pdf import pisa

    receipt = get_or_create_booking_receipt(booking=booking)
    booking.refresh_from_db()
    plot = booking.plot
    lead = booking.lead
    html = f"""
    <html><body>
      <h1>Booking Receipt</h1>
      <p><b>Receipt number:</b> {receipt.receipt_number}</p>
      <p><b>Organization:</b> {booking.organization.name}</p>
      <p><b>Customer:</b> {lead.full_name}</p>
      <p><b>Plot:</b> {plot.block.name} / {plot.plot_number}</p>
      <p><b>Booking date:</b> {timezone.localtime(booking.created_at):%d %B %Y}</p>
      <p><b>Amount:</b> {booking.final_price or '0.00'}</p>
    </body></html>
    """
    result = io.BytesIO()
    status = pisa.CreatePDF(io.BytesIO(html.encode("utf-8")), dest=result, encoding="utf-8")
    if status.err:
        raise ValidationError({"receipt": "Failed to generate booking receipt PDF."})
    response = HttpResponse(result.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="booking_receipt_{receipt.receipt_number}.pdf"'
    response["X-Receipt-Number"] = receipt.receipt_number
    return response
