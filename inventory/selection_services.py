from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Plot, PlotSelection


def is_plot_selectable(plot):
    """Phase 3 has a single currently selectable inventory state: available."""
    return plot.status == Plot.Status.AVAILABLE


def _unavailable(plot):
    return ValidationError({"code": "PLOT_UNAVAILABLE", "message": "This plot is no longer available.", "plot_id": plot.id, "current_status": plot.status, "can_select_another": True})


def _expire_active(plot):
    PlotSelection.objects.filter(plot=plot, status=PlotSelection.Status.ACTIVE, expires_at__lte=timezone.now()).update(status=PlotSelection.Status.EXPIRED, updated_at=timezone.now())


def create_selection(*, organization, plot_id, lead, site_visit, user):
    with transaction.atomic():
        plot = Plot.objects.select_for_update().get(pk=plot_id, organization=organization)
        _expire_active(plot)
        if not is_plot_selectable(plot): raise _unavailable(plot)
        if PlotSelection.objects.filter(plot=plot, status=PlotSelection.Status.ACTIVE, expires_at__gt=timezone.now()).exists():
            raise ValidationError({"code": "PLOT_ALREADY_SELECTED", "message": "This plot has an active selection.", "plot_id": plot.id, "current_status": plot.status, "can_select_another": True})
        selection = PlotSelection(organization=organization, plot=plot, lead=lead, site_visit=site_visit, selected_by=user)
        selection.full_clean(); selection.save(); return selection


def confirm_selection(*, selection):
    with transaction.atomic():
        selection = PlotSelection.objects.select_for_update().select_related("plot", "organization").get(pk=selection.pk)
        plot = Plot.objects.select_for_update().get(pk=selection.plot_id, organization=selection.organization)
        _expire_active(plot); selection.refresh_from_db()
        if selection.status == PlotSelection.Status.CONFIRMED: return selection
        if selection.status != PlotSelection.Status.ACTIVE:
            raise ValidationError({"code": "SELECTION_NOT_ACTIVE", "message": "This selection is no longer active."})
        if not is_plot_selectable(plot): raise _unavailable(plot)
        selection.status = PlotSelection.Status.CONFIRMED; selection.save(update_fields=["status", "updated_at"])
        return selection


def release_selection(*, selection, reason):
    with transaction.atomic():
        selection = PlotSelection.objects.select_for_update().get(pk=selection.pk)
        _expire_active(selection.plot); selection.refresh_from_db()
        if selection.status != PlotSelection.Status.ACTIVE: raise ValidationError({"code": "SELECTION_NOT_ACTIVE", "message": "Only active selections can be released."})
        selection.status = PlotSelection.Status.RELEASED; selection.released_at = timezone.now(); selection.released_reason = (reason or "").strip()
        selection.save(update_fields=["status", "released_at", "released_reason", "updated_at"]); return selection
