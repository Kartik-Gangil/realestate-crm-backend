import os
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.db import transaction
from django.db.models import Prefetch, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from organizations.services import apply_data_scope, get_organization_access, get_project_context, has_permission, is_organization_admin, membership_role_code

from leads.models import Lead, Sitevisit
from leads.views import _leads_for_access, _site_visits_for_access
from documents.models import CustomerDocument

from .models import (Agreement, AgreementSignedDocument, Block, Customer, CustomerNote, Installment, InstallmentPayment, Payment, PaymentAdjustment,
    PaymentAdvance, PaymentAllocation, PaymentReceipt, PaymentRefund, Plot, PlotBooking, PlotHold, PlotSelection,
    Possession, Project, RecentlyViewedPlot, Registry, RegistryCharge, RegistryDocument)
from .serializers import PlotWriteSerializer , BlockWriteSerializer
from .services import (
    block_plot, bulk_change_plot_status, cancel_plot_booking, change_plot_status,
    confirm_plot_booking, create_idempotent_booking, create_plot_booking, hold_plot, release_plot,
)
from .customer_services import (
    CustomerDuplicateError,
    advance_customer_lifecycle,
    create_customer,
    customer_360_data,
    customer_queryset_for_access,
    customer_to_dict,
    set_customer_status,
    update_customer_identity,
)
from system_settings.audit import log_bulk_audit
from .phase5_services import (
    allocate_payment, confirm_payment, create_agreement, create_installment, create_payment,
    adjust_payment, approve_refund, create_allocated_payment, create_possession, create_registry, fail_payment,
    payment_totals, refund_payment,
    transition_agreement, transition_possession, transition_registry,
)
from system_settings.services import clone_project_defaults
from core.files import DOCUMENT_KINDS, private_file_response, validate_upload
from core.endpoint import crm_endpoint
from .selection_services import confirm_selection, create_selection, is_plot_selectable, release_selection
from .receipt_pdf import booking_receipt_pdf, payment_receipt_filename, payment_receipt_pdf


def _validation_response(error):
    if hasattr(error, "message_dict"):
        details = error.message_dict
    elif hasattr(error, "messages"):
        details = {"detail": error.messages}
    else:
        details = {"detail": [str(error)]}
    response_status = status.HTTP_409_CONFLICT if getattr(error, "code", "") in {"idempotency_conflict", "plot_conflict"} else status.HTTP_400_BAD_REQUEST
    return Response(details, status=response_status)


def project_to_dict(project):
    return {
        "id": project.id,
        "name": project.name,
        "code": project.code,
        "description": project.description,
        "organization_id": project.organization_id,
        "organization_slug": project.organization.slug,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


@crm_endpoint(["GET", "POST"], scope="organization")
def project_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    projects = Project.objects.filter(organization=access.organization)
    if not access.is_platform and not is_organization_admin(access.membership):
        projects = projects.filter(assigned_memberships=access.membership)
    if request.method == "GET":
        return Response({
            "count": projects.count(),
            "results": [project_to_dict(project) for project in projects],
        })

    if not access.is_platform and not is_organization_admin(access.membership):
        raise PermissionDenied("Only organization admins and authorized platform users can create projects.")
    name = str(request.data.get("name", "")).strip()
    code = str(request.data.get("code", "")).strip()
    if not name or not code:
        errors = {}
        if not name:
            errors["name"] = "This field is required."
        if not code:
            errors["code"] = "This field is required."
        return Response(errors, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        project = Project.objects.create(
            organization=access.organization,
            name=name,
            code=code,
            description=str(request.data.get("description", "")),
        )
        clone_project_defaults(project, request=request)
    return Response(project_to_dict(project), status=status.HTTP_201_CREATED)


def _plots_for_access(access, project=None, include_active_hold=False):
    queryset = Plot.objects.filter(organization=access.organization).select_related(
        "organization", "block", "created_by"
    )
    if project is not None:
        queryset = queryset.filter(project=project)
    queryset = apply_data_scope(queryset, access, module="plots", user_lookups=("created_by",))
    if include_active_hold:
        queryset = queryset.prefetch_related(
            Prefetch(
                "hold_records",
                queryset=PlotHold.objects.filter(released_at__isnull=True).select_related("created_by"),
                to_attr="active_hold_records",
            )
        )
    return queryset


def _related_to_dict(instance, include_code=False):
    data = {"id": instance.id, "name": instance.name}
    if include_code:
        data["code"] = instance.code
    return data


def _blocks_for_access(access, project=None):
    queryset = Block.objects.filter(organization=access.organization).select_related("organization")
    if project is not None:
        queryset = queryset.filter(project=project)
    return apply_data_scope(queryset, access, module="plots", user_lookups=("plots__created_by",))


def block_to_dict(block, detailed=False):
    data = {
        "id": block.id,
        "name": block.name,
        "code": block.code,
        "project": _related_to_dict(block.project, include_code=True) if block.project_id else None,
    }
    if detailed:
        data.update(
            {
                "organization": {"id": block.organization_id, "name": block.organization.name, "slug": block.organization.slug},
                "created_at": block.created_at.isoformat() if block.created_at else None,
                "updated_at": block.updated_at.isoformat() if block.updated_at else None,
            }
        )
    return data


def _filter_blocks(queryset, params):
    if search := params.get("search"):
        queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
    return queryset


def plot_to_dict(plot, detailed=False):
    active_hold = plot.active_hold_records[0] if getattr(plot, "active_hold_records", None) else plot.hold_records.filter(released_at__isnull=True).order_by("-created_at", "-id").first()
    data = {
        "id": plot.id,
        "plot_number": plot.plot_number,
        "block": _related_to_dict(plot.block, include_code=True),
        "project": _related_to_dict(plot.project, include_code=True) if plot.project_id else None,
        "size": str(plot.size),
        "plot_type": plot.plot_type,
        "status": plot.status,
        "rate_per_sq_unit": str(plot.rate_per_sq_unit) if plot.rate_per_sq_unit is not None else None,
        "total_price": str(plot.total_price) if plot.total_price is not None else None,
        "active_hold": plot_hold_to_dict(active_hold) if active_hold else None,
    }
    if detailed:
        data.update(
            {
                "organization": {
                    "id": plot.organization_id,
                    "name": plot.organization.name,
                    "slug": plot.organization.slug,
                },
                "facing": plot.facing,
                "dimensions": plot.dimensions,
                "description": plot.description,
                "created_by": (
                    {
                        "id": plot.created_by_id,
                        "email": plot.created_by.email,
                        "name": plot.created_by.get_full_name(),
                    }
                    if plot.created_by_id
                    else None
                ),
                "created_at": plot.created_at.isoformat() if plot.created_at else None,
                "updated_at": plot.updated_at.isoformat() if plot.updated_at else None,
                "active_hold": plot_hold_to_dict(plot.active_hold_records[0]) if getattr(plot, "active_hold_records", []) else None,
            }
        )
    return data


def plot_hold_to_dict(plot_hold):
    return {
        "id": plot_hold.id,
        "action_type": plot_hold.action_type,
        "reason": plot_hold.reason,
        "from_datetime": plot_hold.from_datetime.isoformat() if plot_hold.from_datetime else None,
        "to_datetime": plot_hold.to_datetime.isoformat() if plot_hold.to_datetime else None,
        "expires_at": plot_hold.expires_at.isoformat() if plot_hold.expires_at else None,
        "notes": plot_hold.notes,
        "created_by": (
            {"id": plot_hold.created_by_id, "name": plot_hold.created_by.get_full_name()}
            if plot_hold.created_by_id else None
        ),
        "created_at": plot_hold.created_at.isoformat(),
        "released_at": plot_hold.released_at.isoformat() if plot_hold.released_at else None,
    }


def plot_history_to_dict(history):
    return {
        "id": history.id,
        "old_status": history.old_status,
        "new_status": history.new_status,
        "reason": history.reason,
        "changed_by": (
            {"id": history.changed_by_id, "name": history.changed_by.get_full_name()}
            if history.changed_by_id else None
        ),
        "changed_at": history.changed_at.isoformat(),
    }


def _parse_positive_id(params, name):
    raw_value = params.get(name)
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as error:
        raise ValidationError({name: "Use a valid numeric ID."}) from error
    if value < 1:
        raise ValidationError({name: "Use a valid numeric ID."})
    return value


def _filter_plots(queryset, params, organization, active_project=None):
    project_id = _parse_positive_id(params, "project")
    if project_id is not None:
        project = Project.objects.filter(pk=project_id, organization=organization).first()
        if project is None:
            raise ValidationError({"project": "Use a project in this organization."})
        if active_project is not None and project.id != active_project.id:
            raise ValidationError({"project": "The project filter must match X-Project-ID."})
        queryset = queryset.filter(project=project)
    block_id = _parse_positive_id(params, "block")
    if block_id is not None:
        block = Block.objects.filter(pk=block_id, organization=organization).first()
        if block is None:
            raise ValidationError({"block": "Use a block in this organization."})
        if project_id is not None and block.project_id and block.project_id != project_id:
            raise ValidationError({"block": "Block must belong to the selected project."})
        queryset = queryset.filter(block=block)
    if status_value := params.get("status"):
        if status_value not in Plot.Status.values:
            raise ValidationError({"status": "Use a valid plot status."})
        queryset = queryset.filter(status=status_value)
    if plot_type := params.get("plot_type"):
        if plot_type not in Plot.PlotType.values:
            raise ValidationError({"plot_type": "Use a valid plot type."})
        queryset = queryset.filter(plot_type=plot_type)
    if search := params.get("search"):
        queryset = queryset.filter(
            Q(plot_number__icontains=search)
            | Q(block__name__icontains=search)
            | Q(block__code__icontains=search)
            | Q(project__name__icontains=search)
            | Q(project__code__icontains=search)
        )
    return queryset


def _paginate(queryset, params):
    try:
        page = max(int(params.get("page", 1)), 1)
        page_size = min(max(int(params.get("page_size", 25)), 1), 100)
    except (TypeError, ValueError) as error:
        raise ValidationError({"page": "Page and page_size must be integers."}) from error
    count = queryset.count()
    start = (page - 1) * page_size
    return count, page, page_size, queryset[start:start + page_size]


def _page_url(request, page, page_size):
    query = request.query_params.copy()
    query["page"] = page
    query["page_size"] = page_size
    return f"{request.build_absolute_uri(request.path)}?{query.urlencode()}"


def _reject_protected_payload_fields(payload):
    if "status" in payload:
        raise ValidationError({"status": "Status changes must use the inventory status operation."})
    protected = set(payload) & {"id", "organization", "organization_id", "created_by", "created_by_id"}
    if protected:
        raise ValidationError({field: "This field cannot be updated." for field in protected})


def _require_inventory_management(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "plots.edit", project=getattr(access, "project", None)):
        raise PermissionDenied("Only organization admins, managers, and authorized platform users can change plot status.")


def _require_booking_creation(access):
    if access.is_platform:
        return
    if not has_permission(access.membership.user, access.organization, "plots.book", project=getattr(access, "project", None)):
        raise PermissionDenied("This role does not have permission to initiate bookings.")


def _require_booking_lead_scope(access, lead, site_visit):
    role_code = membership_role_code(access.membership)
    if role_code in {"admin", "manager"} or access.is_platform:
        return
    if role_code == "telecaller" and lead.assigned_membership_id == access.membership.id:
        return
    if role_code == "site-visit-executive" and site_visit and site_visit.executive_membership_id == access.membership.id:
        return
    raise PermissionDenied("This role may only book its assigned or executed site-visit leads.")


def _require_inventory_view(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "plots.view", project=getattr(access, "project", None)):
        raise PermissionDenied("This role does not have permission to view Plot Inventory.")


def _require_inventory_create(access):
    if not access.is_platform and not has_permission(
        access.membership.user,
        access.organization,
        "plots.add",
        project=getattr(access, "project", None),
    ):
        raise PermissionDenied("This role does not have permission to create plots.")


def _bookings_for_access(access, project=None):
    queryset = PlotBooking.objects.filter(organization=access.organization)
    if project is not None:
        queryset = queryset.filter(plot__project=project)
    queryset = apply_data_scope(
        queryset,
        access,
        module="plots",
        membership_lookups=("lead__assigned_membership", "site_visit__executive_membership"),
        user_lookups=("created_by",),
    )
    return queryset.select_related(
        "organization", "project", "customer", "lead", "plot", "plot__block", "site_visit", "created_by", "agreement"
    )


def _actor_to_dict(user):
    return {"id": user.id, "email": user.email, "name": user.get_full_name()} if user else None


def booking_to_dict(booking, detailed=False):
    plot, lead = booking.plot, booking.lead
    agreement = getattr(booking, "agreement", None)
    data = {
        "id": booking.id, "booking_code": booking.booking_code or f"BKG-{booking.id}",
        "booking_receipt_number": booking.booking_receipt_number or None,
        "status": booking.status, "notes": booking.notes, "plot_status": plot.status,
        "customer": ({"id": booking.customer_id, "customer_code": booking.customer.customer_code, "full_name": booking.customer.full_name, "phone": booking.customer.phone, "email": booking.customer.email} if booking.customer_id else None),
        "lead": {"id": lead.id, "first_name": lead.first_name, "last_name": lead.last_name,
                 "full_name": lead.full_name, "phone": lead.phone, "email": lead.email},
        "plot": {"id": plot.id, "plot_number": plot.plot_number, "size": str(plot.size),
                 "plot_type": plot.plot_type, "status": plot.status,
                 "rate_per_sq_unit": str(plot.rate_per_sq_unit) if plot.rate_per_sq_unit is not None else None,
                 "total_price": str(plot.total_price) if plot.total_price is not None else None,
                 "block": {"id": plot.block_id, "name": plot.block.name, "code": plot.block.code}},
        "site_visit": ({"id": booking.site_visit_id,
                        "visit_date": booking.site_visit.visit_date.isoformat() if booking.site_visit.visit_date else None,
                        "visit_time": booking.site_visit.visit_time.isoformat() if booking.site_visit.visit_time else None,
                        "site": booking.site_visit.site, "location": booking.site_visit.location}
                       if booking.site_visit_id else None),
        "created_by": _actor_to_dict(booking.created_by),
        "created_at": booking.created_at.isoformat(), "updated_at": booking.updated_at.isoformat(),
        "agreement": agreement_to_dict(agreement) if agreement else None,
    }
    if detailed:
        data.update({"organization": {"id": booking.organization_id, "name": booking.organization.name, "slug": booking.organization.slug},
                     "cancellation_reason": booking.cancellation_reason or None,
                     "hold_expires_at": booking.hold_expires_at.isoformat() if booking.hold_expires_at else None,
                     "financial_summary": {key: str(value) if value is not None else None for key, value in payment_totals(booking).items()},
                     "payments": [payment_to_dict(payment) for payment in booking.payments.select_related("received_by").all()],
                     "installments": [installment_to_dict(item) for item in booking.installments.all()],
                     "agreement": agreement_to_dict(agreement) if agreement else None,
                     "registry": registry_to_dict(booking.registry) if hasattr(booking, "registry") else None,
                     "possession": possession_to_dict(booking.possession) if hasattr(booking, "possession") else None})
    return data


def _booking_payload(request, organization, access, *, project=None, plot_id=None):
    protected = set(request.data) & {"id", "organization", "organization_id", "created_by", "created_by_id", "status"}
    if protected:
        raise ValidationError({field: "This field cannot be supplied." for field in protected})
    lead_id = _parse_positive_id(request.data, "lead_id")
    customer_id = _parse_positive_id(request.data, "customer_id")
    supplied_plot_id = _parse_positive_id(request.data, "plot_id")
    if plot_id is not None and supplied_plot_id is not None and supplied_plot_id != plot_id:
        raise ValidationError({"plot_id": "Must match the plot in the URL."})
    selected_plot_id = plot_id if plot_id is not None else supplied_plot_id
    if lead_id is None:
        raise ValidationError({"lead_id": "This field is required."})
    if selected_plot_id is None:
        raise ValidationError({"plot_id": "This field is required."})
    site_visit_id = _parse_positive_id(request.data, "site_visit_id")
    lead = get_object_or_404(_leads_for_access(access, project), pk=lead_id)
    customer = None
    if customer_id is not None:
        customer = get_object_or_404(customer_queryset_for_access(access, project), pk=customer_id)
        if customer.lead_id and customer.lead_id != lead.id:
            raise ValidationError({"customer_id": "Customer must belong to the selected lead."})
    plot = get_object_or_404(_plots_for_access(access, project), pk=selected_plot_id)
    site_visit = get_object_or_404(
        _site_visits_for_access(access, _leads_for_access(access, project), project).filter(pk=site_visit_id),
    ) if site_visit_id else None
    return lead, customer, plot, site_visit, str(request.data.get("notes", "")).strip()


def _filter_bookings(queryset, params, organization):
    if status_value := params.get("status"):
        if status_value not in PlotBooking.Status.values:
            raise ValidationError({"status": "Use a valid booking status."})
        queryset = queryset.filter(status=status_value)
    for field in ("plot", "lead", "block"):
        value = _parse_positive_id(params, field)
        if value is not None:
            lookup = {"plot": "plot_id", "lead": "lead_id", "block": "plot__block_id"}[field]
            queryset = queryset.filter(**{lookup: value})
    if search := params.get("search"):
        queryset = queryset.filter(Q(lead__first_name__icontains=search) | Q(lead__last_name__icontains=search)
            | Q(lead__phone__icontains=search) | Q(lead__email__icontains=search)
            | Q(plot__plot_number__icontains=search) | Q(plot__block__name__icontains=search))
    return queryset


def _parse_operation_payload(payload):
    def parse_value(name):
        value = payload.get(name)
        if value in (None, ""):
            return None
        parsed = parse_datetime(value) if isinstance(value, str) else value
        if parsed is None or not timezone.is_aware(parsed):
            raise ValidationError({name: "Use a timezone-aware ISO 8601 datetime."})
        return parsed

    return {
        "reason": str(payload.get("reason", "")).strip(),
        "from_datetime": parse_value("from_datetime"),
        "to_datetime": parse_value("to_datetime"),
        "notes": str(payload.get("notes", "")).strip(),
    }


def _plot_response(access, plot, project=None):
    plot = _plots_for_access(access, project, include_active_hold=True).get(pk=plot.pk)
    return Response(plot_to_dict(plot, detailed=True))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def block_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if request.method == "GET":
        _require_inventory_view(access)
    if request.method == "POST":
        try:
            _reject_protected_payload_fields(request.data)
        except ValidationError as error:
            return _validation_response(error)
        payload = request.data.copy()
        requested_project = payload.get("project")
        if requested_project not in (None, "") and str(requested_project) != str(project.id):
            return _validation_response(ValidationError({"project": "Project must match X-Project-ID."}))
        payload["project"] = project.id
        serializer = BlockWriteSerializer(
            data=payload, context={"organization": access.organization, "request": request}
        )
        serializer.is_valid(raise_exception=True)
        block = serializer.save()
        block = _blocks_for_access(access, project).get(pk=block.pk)
        return Response(block_to_dict(block, detailed=True), status=status.HTTP_201_CREATED)

    try:
        blocks = _filter_blocks(_blocks_for_access(access, project), request.query_params)
        count, page, page_size, results = _paginate(blocks, request.query_params)
    except ValidationError as error:
        return _validation_response(error)
    return Response(
        {
            "count": count,
            "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
            "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
            "results": [block_to_dict(block) for block in results],
        }
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def block_detail(request, organization_slug, block_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    block = get_object_or_404(_blocks_for_access(access, project), pk=block_id)
    if request.method == "GET":
        return Response(block_to_dict(block, detailed=True))

    try:
        _reject_protected_payload_fields(request.data)
    except ValidationError as error:
        return _validation_response(error)
    serializer = BlockWriteSerializer(
        block,
        data=request.data,
        partial=True,
        context={"organization": access.organization, "request": request},
    )
    serializer.is_valid(raise_exception=True)
    block = serializer.save()
    block = _blocks_for_access(access, project).get(pk=block.pk)
    return Response(block_to_dict(block, detailed=True))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def plot_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if request.method == "GET":
        _require_inventory_view(access)
    if request.method == "POST":
        _require_inventory_create(access)
        try:
            _reject_protected_payload_fields(request.data)
        except ValidationError as error:
            return _validation_response(error)
        payload = request.data.copy()
        requested_project = payload.get("project")
        if requested_project not in (None, "") and str(requested_project) != str(project.id):
            return _validation_response(ValidationError({"project": "Project must match X-Project-ID."}))
        payload["project"] = project.id
        serializer = PlotWriteSerializer(
            data=payload, context={"organization": access.organization, "request": request}
        )
        serializer.is_valid(raise_exception=True)
        plot = serializer.save()
        plot = _plots_for_access(access, project, include_active_hold=True).get(pk=plot.pk)
        return Response(plot_to_dict(plot, detailed=True), status=status.HTTP_201_CREATED)

    try:
        plots = _filter_plots(_plots_for_access(access, project), request.query_params, access.organization, project)
        count, page, page_size, results = _paginate(plots, request.query_params)
    except ValidationError as error:
        return _validation_response(error)
    return Response(
        {
            "count": count,
            "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
            "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
            "results": [plot_to_dict(plot) for plot in results],
        }
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def plot_detail(request, organization_slug, plot_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    plot = get_object_or_404(_plots_for_access(access, project, include_active_hold=True), pk=plot_id)
    if request.method == "GET":
        _require_inventory_view(access)
        return Response(plot_to_dict(plot, detailed=True))

    _require_inventory_management(access)

    try:
        _reject_protected_payload_fields(request.data)
    except ValidationError as error:
        return _validation_response(error)
    serializer = PlotWriteSerializer(
        plot,
        data=request.data,
        partial=True,
        context={"organization": access.organization, "request": request},
    )
    serializer.is_valid(raise_exception=True)
    plot = serializer.save()
    plot = _plots_for_access(access, project, include_active_hold=True).get(pk=plot.pk)
    return Response(plot_to_dict(plot, detailed=True))


def _status_operation(request, organization_slug, plot_id, operation):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if operation == "hold":
        if not access.is_platform and not has_permission(
            access.membership.user, access.organization, "plots.hold", project=getattr(access, "project", None)
        ) and not has_permission(
            access.membership.user, access.organization, "plots.edit", project=getattr(access, "project", None)
        ):
            raise PermissionDenied("This role does not have permission to request a plot hold.")
    else:
        _require_inventory_management(access)
    plot = get_object_or_404(_plots_for_access(access, project), pk=plot_id)
    try:
        payload = _parse_operation_payload(request.data)
        if operation == "status":
            plot = change_plot_status(plot=plot, new_status=request.data.get("status"), user=request.user, **payload)
        elif operation == "block":
            plot = block_plot(plot=plot, user=request.user, **payload)
        elif operation == "hold":
            plot = hold_plot(plot=plot, user=request.user, **payload)
        else:
            plot = release_plot(plot=plot, reason=payload["reason"], user=request.user, request=request)
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return _plot_response(access, plot, project)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plot_status(request, organization_slug, plot_id):
    return _status_operation(request, organization_slug, plot_id, "status")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plot_block(request, organization_slug, plot_id):
    return _status_operation(request, organization_slug, plot_id, "block")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plot_hold(request, organization_slug, plot_id):
    return _status_operation(request, organization_slug, plot_id, "hold")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plot_release(request, organization_slug, plot_id):
    return _status_operation(request, organization_slug, plot_id, "release")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def plot_history(request, organization_slug, plot_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    plot = get_object_or_404(_plots_for_access(access, project), pk=plot_id)
    try:
        history = plot.status_history.select_related("changed_by").all()
        count, page, page_size, results = _paginate(history, request.query_params)
    except ValidationError as error:
        return _validation_response(error)
    return Response(
        {
            "count": count,
            "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
            "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
            "results": [plot_history_to_dict(item) for item in results],
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plot_bulk_status(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_inventory_management(access)
    plot_ids = request.data.get("plot_ids")
    if not isinstance(plot_ids, list) or not plot_ids:
        return Response({"plot_ids": ["Provide a non-empty list of plot IDs."]}, status=status.HTTP_400_BAD_REQUEST)
    if len(set(plot_ids)) != len(plot_ids):
        return Response({"plot_ids": ["Plot IDs must not contain duplicates."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        numeric_ids = [int(plot_id) for plot_id in plot_ids]
        if any(plot_id < 1 for plot_id in numeric_ids):
            raise ValueError
    except (TypeError, ValueError):
        return Response({"plot_ids": ["Use valid numeric plot IDs."]}, status=status.HTTP_400_BAD_REQUEST)
    plots = list(_plots_for_access(access, project).filter(pk__in=numeric_ids))
    if len(plots) != len(numeric_ids):
        return Response({"plot_ids": ["One or more plots do not exist in this organization."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        updated = bulk_change_plot_status(
            plots=plots, new_status=request.data.get("status"), reason=str(request.data.get("reason", "")).strip(), user=request.user
        )
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    updated_by_id = {plot.id: plot for plot in updated}
    response_plots = [
        _plots_for_access(access, project, include_active_hold=True).get(pk=plot_id)
        for plot_id in sorted(updated_by_id)
    ]
    return Response({"updated": len(response_plots), "plots": [plot_to_dict(plot, detailed=True) for plot in response_plots]})


def _booking_page_response(request, bookings):
    count, page, page_size, results = _paginate(bookings, request.query_params)
    return Response({"count": count, "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
                     "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
                     "results": [booking_to_dict(booking) for booking in results]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plot_select(request, organization_slug, plot_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_booking_creation(access)
    try:
        lead, customer, plot, site_visit, notes = _booking_payload(request, access.organization, access, project=project, plot_id=plot_id)
        if plot.project_id != project.id:
            raise ValidationError({"plot_id": "Plot does not belong to the active project."})
        _require_booking_lead_scope(access, lead, site_visit)
        booking = create_idempotent_booking(
            organization=access.organization, project=project, lead=lead, customer=customer, plot=plot, user=request.user,
            idempotency_key=request.headers.get("X-Idempotency-Key"), body=dict(request.data),
            site_visit=site_visit, notes=notes, initial_payment=request.data.get("initial_payment", "0"),
            payment_mode=request.data.get("payment_mode"), transaction_reference=request.data.get("transaction_reference", ""),
        )
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response(booking_to_dict(_bookings_for_access(access, project).get(pk=booking.pk), detailed=True), status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def booking_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if request.method == "POST":
        _require_booking_creation(access)
        try:
            lead, customer, plot, site_visit, notes = _booking_payload(request, access.organization, access, project=project)
            if plot.project_id != project.id:
                raise ValidationError({"plot_id": "Plot does not belong to the active project."})
            _require_booking_lead_scope(access, lead, site_visit)
            booking = create_idempotent_booking(
                organization=access.organization, project=project, lead=lead, customer=customer, plot=plot, user=request.user,
                idempotency_key=request.headers.get("X-Idempotency-Key"), body=dict(request.data),
                site_visit=site_visit, notes=notes, initial_payment=request.data.get("initial_payment", "0"),
                payment_mode=request.data.get("payment_mode"), transaction_reference=request.data.get("transaction_reference", ""),
            )
        except (ValidationError, ValueError, TypeError) as error:
            return _validation_response(error)
        return Response(booking_to_dict(_bookings_for_access(access, project).get(pk=booking.pk), detailed=True), status=status.HTTP_201_CREATED)
    try:
        return _booking_page_response(request, _filter_bookings(_bookings_for_access(access, project), request.query_params, access.organization))
    except ValidationError as error:
        return _validation_response(error)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def booking_detail(request, organization_slug, booking_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    return Response(booking_to_dict(get_object_or_404(_bookings_for_access(access, project), pk=booking_id), detailed=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def booking_confirm(request, organization_slug, booking_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_inventory_management(access)
    booking = get_object_or_404(_bookings_for_access(access, project), pk=booking_id)
    try:
        booking = confirm_plot_booking(booking=booking, user=request.user)
    except (ValidationError, ValueError, TypeError) as error:
        if hasattr(error, "document_validation"):
            return Response({"detail": "Customer documents are incomplete.", "document_validation": error.document_validation}, status=status.HTTP_400_BAD_REQUEST)
        return _validation_response(error)
    return Response(booking_to_dict(_bookings_for_access(access, project).get(pk=booking.pk), detailed=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def booking_cancel(request, organization_slug, booking_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_inventory_management(access)
    booking = get_object_or_404(_bookings_for_access(access, project), pk=booking_id)
    try:
        booking = cancel_plot_booking(booking=booking, reason=str(request.data.get("reason", "")).strip(), user=request.user)
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response(booking_to_dict(_bookings_for_access(access, project).get(pk=booking.pk), detailed=True))


@crm_endpoint(["GET"], scope="organization")
def booking_receipt(request, organization_slug, booking_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    booking = get_object_or_404(_bookings_for_access(access, project), pk=booking_id)
    response = HttpResponse(booking_receipt_pdf(booking), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="Booking_{booking.booking_receipt_number or booking.booking_code or booking.id}.pdf"'
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lead_bookings(request, organization_slug, lead_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    lead = get_object_or_404(_leads_for_access(access, project), pk=lead_id)
    try:
        return _booking_page_response(request, _filter_bookings(_bookings_for_access(access, project).filter(lead=lead), request.query_params, access.organization))
    except ValidationError as error:
        return _validation_response(error)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def plot_bookings(request, organization_slug, plot_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    plot = get_object_or_404(_plots_for_access(access, project), pk=plot_id)
    try:
        return _booking_page_response(request, _filter_bookings(_bookings_for_access(access, project).filter(plot=plot), request.query_params, access.organization))
    except ValidationError as error:
        return _validation_response(error)


def _selection_to_dict(selection):
    return {"id": selection.id, "plot": {"id": selection.plot_id, "plot_number": selection.plot.plot_number, "status": selection.plot.status},
            "lead": {"id": selection.lead_id, "full_name": selection.lead.full_name} if selection.lead_id else None,
            "site_visit": {"id": selection.site_visit_id} if selection.site_visit_id else None,
            "status": selection.status, "selected_by": _actor_to_dict(selection.selected_by),
            "selected_at": selection.selected_at.isoformat(), "expires_at": selection.expires_at.isoformat() if selection.expires_at else None,
            "released_at": selection.released_at.isoformat() if selection.released_at else None, "released_reason": selection.released_reason or None}


def _selection_queryset(access, project=None):
    queryset = PlotSelection.objects.filter(organization=access.organization).select_related("plot", "lead", "site_visit", "selected_by")
    if project is not None:
        queryset = queryset.filter(plot__project=project)
    return apply_data_scope(
        queryset,
        access,
        module="plots",
        membership_lookups=("lead__assigned_membership", "site_visit__executive_membership"),
        user_lookups=("selected_by",),
    )


def _selection_response(error):
    details = error.message_dict if hasattr(error, "message_dict") else {}
    if "code" in details:
        return Response({key: value[0] if isinstance(value, list) and len(value) == 1 else value for key, value in details.items()}, status=status.HTTP_409_CONFLICT)
    return _validation_response(error)


def _validate_inventory_context(params, organization, access=None):
    lead_id, visit_id = _parse_positive_id(params, "lead_id"), _parse_positive_id(params, "site_visit_id")
    lead_queryset = _leads_for_access(access) if access else Lead.objects.filter(organization=organization)
    lead = get_object_or_404(lead_queryset, pk=lead_id) if lead_id else None
    if access:
        visit_queryset = _site_visits_for_access(access, _leads_for_access(access))
    else:
        visit_queryset = Sitevisit.objects.filter(organization=organization)
    visit = get_object_or_404(visit_queryset, pk=visit_id) if visit_id else None
    if lead and visit and visit.lead_id != lead.id: raise ValidationError({"site_visit_id": "Site visit must belong to the selected lead."})
    return lead, visit


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def plot_inventory(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    try:
        _validate_inventory_context(request.query_params, access.organization, access)
        project = get_project_context(request, access)
        plots = _filter_plots(_plots_for_access(access, project, include_active_hold=True), request.query_params, access.organization, project)
        if facing := request.query_params.get("facing"): plots = plots.filter(facing__iexact=facing)
        if request.query_params.get("available", "").lower() in {"true", "1"}: plots = plots.filter(status=Plot.Status.AVAILABLE)
        if min_size := request.query_params.get("min_size"): plots = plots.filter(size__gte=min_size)
        if max_size := request.query_params.get("max_size"): plots = plots.filter(size__lte=max_size)
        count, page, page_size, results = _paginate(plots, request.query_params)
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response({"count": count, "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
                     "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
                     "results": [{**plot_to_dict(plot), "facing": plot.facing, "available": is_plot_selectable(plot)} for plot in results]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def plot_inventory_detail(request, organization_slug, plot_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); plot = get_object_or_404(_plots_for_access(access, project, include_active_hold=True), pk=plot_id)
    RecentlyViewedPlot.objects.update_or_create(organization=access.organization, user=request.user, plot=plot)
    data = plot_to_dict(plot, detailed=True); data["available"] = is_plot_selectable(plot)
    if plot.status != Plot.Status.AVAILABLE:
        hold = getattr(plot, "active_hold_records", [])
        data["blocking_info"] = {"blocked": True, "status": plot.status, "blocked_on": hold[0].created_at.isoformat() if hold else None, "reason": hold[0].reason if hold else "Plot is not available."}
    else: data["blocking_info"] = None
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def plot_inventory_availability(request, organization_slug, plot_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    plot = get_object_or_404(_plots_for_access(access, project), pk=plot_id)
    available = is_plot_selectable(plot) and not _selection_queryset(access, project).filter(plot=plot, status=PlotSelection.Status.ACTIVE, expires_at__gt=timezone.now()).exists()
    data = {"plot_id": plot.id, "available": available, "status": plot.status}
    if not available: data.update({"reason": "Plot is no longer available.", "can_select_another": True})
    return Response(data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plot_inventory_select(request, organization_slug, plot_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_inventory_management(access)
    try:
        lead, visit = _validate_inventory_context(request.data, access.organization, access)
        get_object_or_404(_plots_for_access(access, project), pk=plot_id)
        selection = create_selection(organization=access.organization, plot_id=plot_id, lead=lead, site_visit=visit, user=request.user)
    except Plot.DoesNotExist: return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    except (ValidationError, ValueError, TypeError) as error: return _selection_response(error)
    return Response(_selection_to_dict(_selection_queryset(access, project).get(pk=selection.pk)), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def selection_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); selections = _selection_queryset(access, project)
    try:
        if value := request.query_params.get("status"):
            if value not in PlotSelection.Status.values: raise ValidationError({"status": "Use a valid selection status."})
            selections = selections.filter(status=value)
        count, page, page_size, results = _paginate(selections, request.query_params)
    except ValidationError as error: return _validation_response(error)
    return Response({"count": count, "next": _page_url(request, page + 1, page_size) if page * page_size < count else None, "previous": _page_url(request, page - 1, page_size) if page > 1 else None, "results": [_selection_to_dict(item) for item in results]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def selection_detail(request, organization_slug, selection_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    return Response(_selection_to_dict(get_object_or_404(_selection_queryset(access, project), pk=selection_id)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def selection_confirm(request, organization_slug, selection_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_inventory_management(access); selection = get_object_or_404(_selection_queryset(access, project), pk=selection_id)
    try: selection = confirm_selection(selection=selection)
    except ValidationError as error: return _selection_response(error)
    selection = _selection_queryset(access, project).get(pk=selection.pk); data = _selection_to_dict(selection)
    data.update({"next_action": "BOOKING", "booking_context": {"plot_id": selection.plot_id, "lead_id": selection.lead_id, "site_visit_id": selection.site_visit_id}})
    return Response(data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def selection_release(request, organization_slug, selection_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_inventory_management(access); selection = get_object_or_404(_selection_queryset(access, project), pk=selection_id)
    try: selection = release_selection(selection=selection, reason=str(request.data.get("reason", "")))
    except ValidationError as error: return _selection_response(error)
    return Response(_selection_to_dict(_selection_queryset(access, project).get(pk=selection.pk)))


def _decimal(payload, name):
    try:
        value = Decimal(str(payload.get(name, "")))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValidationError({name: "Use a valid decimal amount."}) from error
    return value


def _date(payload, name, required=True):
    raw = payload.get(name)
    if not raw and not required: return None
    try: return date.fromisoformat(str(raw))
    except (TypeError, ValueError) as error: raise ValidationError({name: "Use YYYY-MM-DD."}) from error


def _sales_queryset(model, access, project=None):
    queryset = model.objects.filter(organization=access.organization)
    if project is not None:
        queryset = queryset.filter(booking__plot__project=project)
    user_lookups = ["booking__created_by"]
    if model in {Agreement, Registry, Possession}:
        user_lookups.append("created_by")
    if model is Payment:
        user_lookups.append("received_by")
    queryset = apply_data_scope(
        queryset,
        access,
        module="payments" if model is Payment else "plots",
        membership_lookups=("booking__lead__assigned_membership",),
        user_lookups=tuple(user_lookups),
    )
    return queryset.select_related("organization", "booking", "booking__lead", "booking__customer", "booking__plot", "booking__plot__block")


def _require_permission(access, code):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, code, project=getattr(access, "project", None)):
        raise PermissionDenied("This role does not have the required permission.")


def _payment_queryset(access, project=None):
    queryset = Payment.objects.filter(organization=access.organization)
    if project is not None:
        queryset = queryset.filter(
            Q(booking__plot__project=project)
            | Q(payment_allocations__booking__plot__project=project)
        ).distinct()
    queryset = apply_data_scope(
        queryset,
        access,
        module="payments",
        membership_lookups=("booking__lead__assigned_membership",),
        user_lookups=("booking__created_by", "received_by"),
    )
    return queryset.select_related("organization", "booking", "booking__lead", "booking__customer", "booking__plot", "booking__plot__block", "received_by").prefetch_related("payment_allocations__booking__lead", "payment_allocations__booking__customer", "payment_allocations__booking__plot__block", "receipt", "refunds")


def _simple_page(request, queryset, serializer):
    if status_value := request.query_params.get("status"):
        queryset = queryset.filter(status=status_value)
    if booking_id := _parse_positive_id(request.query_params, "booking"):
        queryset = queryset.filter(booking_id=booking_id)
    count, page, page_size, results = _paginate(queryset, request.query_params)
    return Response({"count": count, "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
                     "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
                     "results": [serializer(item) for item in results]})


def _booking_has_overdue_balance(booking):
    if payment_totals(booking)["outstanding_amount"] <= 0:
        return False
    for installment in Installment.objects.filter(booking=booking):
        paid = InstallmentPayment.objects.filter(
            installment=installment,
            payment__status__in=[Payment.Status.SUCCESS, Payment.Status.REFUNDED],
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        paid += PaymentAllocation.objects.filter(
            installment=installment,
            payment__status__in=[Payment.Status.SUCCESS, Payment.Status.REFUNDED],
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        if installment.due_date < date.today() and paid < installment.amount:
            return True
    return False


def payment_to_dict(payment, detailed=False):
    allocations = getattr(payment, "payment_allocations", None)
    allocation_rows = list(allocations.all()) if allocations is not None else list(PaymentAllocation.objects.filter(payment=payment).select_related("booking__lead", "booking__customer", "booking__plot", "installment", "registry_charge"))
    context_booking = allocation_rows[0].booking if allocation_rows else getattr(payment, "booking", None)
    context_customer = context_booking.customer if context_booking else None
    context_plot = context_booking.plot if context_booking else None
    refund_rows = list(payment.refunds.all())
    account_status = payment.status
    booking_contexts = {row.booking_id: row.booking for row in allocation_rows}
    if payment.booking_id and payment.booking_id not in booking_contexts:
        booking_contexts[payment.booking_id] = payment.booking
    if any(_booking_has_overdue_balance(booking) for booking in booking_contexts.values()):
        account_status = "overdue"
    advance_rows = list(PaymentAdvance.objects.filter(payment=payment).select_related("booking"))
    data = {"id": payment.id, "payment_id": payment.payment_id or f"PAY-{payment.id}", "booking_id": payment.booking_id or (context_booking.id if context_booking else None), "amount": str(payment.amount), "advance_amount": str(sum((row.amount for row in advance_rows), Decimal("0.00"))), "status": payment.status, "account_status": account_status,
            "payment_method": payment.payment_method, "transaction_reference": payment.transaction_reference,
            "payment_date": payment.payment_date.isoformat(), "notes": payment.notes,
            "customer": ({"id": context_customer.id, "name": context_customer.full_name, "phone": context_customer.phone} if context_customer else None),
            "customer_id": context_customer.id if context_customer else None,
            "plot_number": context_plot.plot_number if context_plot else None,
            "booking": ({"id": context_booking.id, "plot_number": context_plot.plot_number} if context_booking and context_plot else None),
            "booking_ref": f"Booking #{context_booking.id}" if context_booking else None,
            "refunds": [{"id": refund.id, "amount": str(refund.amount), "status": refund.status, "reason": refund.reason, "refund_date": refund.refund_date.isoformat()} for refund in refund_rows],
            "received_by": _actor_to_dict(payment.received_by), "created_at": payment.created_at.isoformat(), "updated_at": payment.updated_at.isoformat()}
    if detailed:
        data.update({"allocations": [{"booking_id": a.booking_id, "amount": str(a.amount), "installment_id": a.installment_id, "registry_charge_id": a.registry_charge_id, "customer": {"id": a.booking.customer_id, "name": a.booking.customer.full_name}, "plot": {"id": a.booking.plot_id, "plot_number": a.booking.plot.plot_number}} for a in allocation_rows],
                     "advances": [{"booking_id": row.booking_id, "amount": str(row.amount)} for row in advance_rows],
                     "receipt": ({"receipt_number": payment.receipt.receipt_number, "generated_at": payment.receipt.generated_at.isoformat()} if hasattr(payment, "receipt") else None),
                     "refunds": [{"id": r.id, "amount": str(r.amount), "reason": r.reason, "status": r.status, "refund_date": r.refund_date.isoformat()} for r in refund_rows]})
    return data


def installment_to_dict(item):
    paid = item.allocations.aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("amount"))["total"] or Decimal("0.00")
    return {"id": item.id, "booking_id": item.booking_id, "installment_number": item.installment_number, "title": item.title,
            "due_date": item.due_date.isoformat(), "amount": str(item.amount), "paid_amount": str(paid), "status": item.status,
            "notes": item.notes, "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat()}


def agreement_to_dict(item):
    signed_copy = item.signed_documents.filter(superseded_at__isnull=True).order_by("-uploaded_at", "-id").first()
    return {"id": item.id, "booking_id": item.booking_id, "agreement_number": item.agreement_number, "agreement_date": item.agreement_date.isoformat() if item.agreement_date else None, "status": item.status, "document_reference": item.document_reference, "notes": item.notes, "has_signed_file": bool(signed_copy), "signed_file_name": signed_copy.original_filename if signed_copy else None, "signed_file_size": signed_copy.file_size_bytes if signed_copy else None, "signed_file_uploaded_at": signed_copy.uploaded_at.isoformat() if signed_copy else None}
def registry_to_dict(item): return {"id": item.id, "booking_id": item.booking_id, "registry_number": item.registry_number, "registry_date": item.registry_date.isoformat() if item.registry_date else None, "status": item.status, "notes": item.notes}
def possession_to_dict(item): return {"id": item.id, "booking_id": item.booking_id, "possession_date": item.possession_date.isoformat() if item.possession_date else None, "status": item.status, "notes": item.notes, "handed_over_by": _actor_to_dict(item.handed_over_by)}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def booking_payments(request, organization_slug, booking_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); booking = get_object_or_404(_bookings_for_access(access, project), pk=booking_id)
    if request.method == "GET": return _simple_page(request, _sales_queryset(Payment, access, project).filter(booking=booking), payment_to_dict)
    _require_inventory_management(access)
    try:
        payment = create_payment(booking=booking, amount=_decimal(request.data, "amount"), payment_method=request.data.get("payment_method"), transaction_reference=request.data.get("transaction_reference"), payment_date=_date(request.data, "payment_date"), notes=request.data.get("notes"), user=request.user)
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response(payment_to_dict(_sales_queryset(Payment, access, project).get(pk=payment.pk), True), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payment_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    return _simple_page(request, _sales_queryset(Payment, access, project), payment_to_dict)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payment_detail(request, organization_slug, payment_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    return Response(payment_to_dict(get_object_or_404(_sales_queryset(Payment, access, project), pk=payment_id), True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def payment_confirm(request, organization_slug, payment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_inventory_management(access); payment = get_object_or_404(_sales_queryset(Payment, access, project), pk=payment_id)
    try: payment = confirm_payment(payment=payment, user=request.user)
    except ValidationError as error: return _validation_response(error)
    return Response(payment_to_dict(_sales_queryset(Payment, access, project).get(pk=payment.pk), True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def payment_fail(request, organization_slug, payment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_inventory_management(access); payment = get_object_or_404(_sales_queryset(Payment, access, project), pk=payment_id)
    try: payment = fail_payment(payment=payment)
    except ValidationError as error: return _validation_response(error)
    return Response(payment_to_dict(_sales_queryset(Payment, access, project).get(pk=payment.pk), True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def payment_refund(request, organization_slug, payment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_inventory_management(access); payment = get_object_or_404(_sales_queryset(Payment, access, project), pk=payment_id)
    try: refund = refund_payment(payment=payment, amount=_decimal(request.data, "amount"), reason=str(request.data.get("reason", "")), refund_date=_date(request.data, "refund_date"), user=request.user)
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response({"id": refund.id, "payment_id": refund.payment_id, "amount": str(refund.amount), "refund_date": refund.refund_date.isoformat()}, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def booking_installments(request, organization_slug, booking_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); booking = get_object_or_404(_bookings_for_access(access, project), pk=booking_id)
    if request.method == "GET": return _simple_page(request, _sales_queryset(Installment, access, project).filter(booking=booking), installment_to_dict)
    _require_inventory_management(access)
    try: item = create_installment(booking=booking, installment_number=int(request.data.get("installment_number")), title=str(request.data.get("title", "")), due_date=_date(request.data, "due_date"), amount=_decimal(request.data, "amount"), notes=str(request.data.get("notes", "")))
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response(installment_to_dict(item), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def installment_detail(request, organization_slug, installment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); item = get_object_or_404(_sales_queryset(Installment, access, project), pk=installment_id)
    if request.method == "GET": return Response(installment_to_dict(item))
    _require_inventory_management(access)
    try:
        if "status" in request.data: raise ValidationError({"status": "Use payment allocation to update installment status."})
        for field in ("title", "notes"): 
            if field in request.data: setattr(item, field, str(request.data[field]))
        if "due_date" in request.data: item.due_date = _date(request.data, "due_date")
        if "amount" in request.data:
            amount = _decimal(request.data, "amount"); paid = item.allocations.aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("amount"))["total"] or Decimal("0")
            if amount <= 0 or amount < paid: raise ValidationError({"amount": "Cannot be less than paid amount."})
            item.amount = amount
        item.full_clean(); item.save()
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response(installment_to_dict(item))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def installment_allocate(request, organization_slug, installment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_inventory_management(access); item = get_object_or_404(_sales_queryset(Installment, access, project), pk=installment_id)
    try:
        payment = get_object_or_404(_sales_queryset(Payment, access, project), pk=_parse_positive_id(request.data, "payment_id")); allocation = allocate_payment(payment=payment, installment=item, amount=_decimal(request.data, "amount"))
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response({"id": allocation.id, "payment_id": allocation.payment_id, "installment_id": allocation.installment_id, "amount": str(allocation.amount)}, status=status.HTTP_201_CREATED)


def _legal_create_or_get(request, access, booking, model, creator, serializer):
    project = get_project_context(request, access)
    if request.method == "GET":
        return Response(serializer(get_object_or_404(_sales_queryset(model, access, project), booking=booking)))
    _require_inventory_management(access)
    try:
        if model is Agreement:
            item = creator(booking=booking, agreement_number=str(request.data.get("agreement_number", "")), agreement_date=_date(request.data, "agreement_date", False), document_reference=str(request.data.get("document_reference", "")), notes=str(request.data.get("notes", "")), created_by=request.user)
        elif model is Registry:
            item = creator(booking=booking, registry_number=str(request.data.get("registry_number", "")), registry_date=_date(request.data, "registry_date", False), notes=str(request.data.get("notes", "")), created_by=request.user)
        else:
            item = creator(booking=booking, possession_date=_date(request.data, "possession_date", False), notes=str(request.data.get("notes", "")), handed_over_by=request.user)
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response(serializer(item), status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def booking_agreement(request, organization_slug, booking_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); booking = get_object_or_404(_bookings_for_access(access, project), pk=booking_id)
    return _legal_create_or_get(request, access, booking, Agreement, create_agreement, agreement_to_dict)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def booking_registry(request, organization_slug, booking_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); booking = get_object_or_404(_bookings_for_access(access, project), pk=booking_id)
    return _legal_create_or_get(request, access, booking, Registry, create_registry, registry_to_dict)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def booking_possession(request, organization_slug, booking_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); booking = get_object_or_404(_bookings_for_access(access, project), pk=booking_id)
    return _legal_create_or_get(request, access, booking, Possession, create_possession, possession_to_dict)


def _legal_detail(request, organization_slug, item_id, model, serializer, editable, transition):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); item = get_object_or_404(_sales_queryset(model, access, project), pk=item_id)
    if request.method == "GET": return Response(serializer(item))
    _require_inventory_management(access)
    try:
        if "status" in request.data: raise ValidationError({"status": "Use a dedicated status operation."})
        for field in editable:
            if field in request.data:
                setattr(item, field, _date(request.data, field) if field in {"agreement_date", "registry_date", "possession_date"} else request.data[field])
        item.full_clean(); item.save()
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response(serializer(item))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def agreement_detail(request, organization_slug, agreement_id): return _legal_detail(request, organization_slug, agreement_id, Agreement, agreement_to_dict, ("agreement_number", "agreement_date", "document_reference", "notes"), transition_agreement)
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def registry_detail(request, organization_slug, registry_id): return _legal_detail(request, organization_slug, registry_id, Registry, registry_to_dict, ("registry_number", "registry_date", "notes"), transition_registry)
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def possession_detail(request, organization_slug, possession_id): return _legal_detail(request, organization_slug, possession_id, Possession, possession_to_dict, ("possession_date", "notes"), transition_possession)


def _legal_transition_view(request, organization_slug, item_id, model, service, target, serializer):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_inventory_management(access); item = get_object_or_404(_sales_queryset(model, access, project), pk=item_id)
    try: item = service(**{model.__name__.lower(): item, "status": target})
    except ValidationError as error: return _validation_response(error)
    return Response(serializer(_sales_queryset(model, access, project).get(pk=item.pk)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agreement_ready(request, organization_slug, agreement_id): return _legal_transition_view(request, organization_slug, agreement_id, Agreement, transition_agreement, Agreement.Status.READY, agreement_to_dict)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agreement_sign(request, organization_slug, agreement_id): return _legal_transition_view(request, organization_slug, agreement_id, Agreement, transition_agreement, Agreement.Status.SIGNED, agreement_to_dict)


def _active_signed_copy(access, agreement_id, project):
    agreement = get_object_or_404(_sales_queryset(Agreement, access, project), pk=agreement_id)
    document = get_object_or_404(AgreementSignedDocument.objects.filter(agreement=agreement, superseded_at__isnull=True).order_by("-uploaded_at", "-id"))
    return agreement, document


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def agreement_signed_copy(request, organization_slug, agreement_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    agreement = get_object_or_404(_sales_queryset(Agreement, access, project), pk=agreement_id)
    if request.method == "GET":
        document = get_object_or_404(AgreementSignedDocument.objects.filter(agreement=agreement, superseded_at__isnull=True).order_by("-uploaded_at", "-id"))
        return Response({"id": document.id, "agreement_id": agreement.id, "original_filename": document.original_filename, "content_type": document.content_type, "file_size_bytes": document.file_size_bytes, "uploaded_by": _actor_to_dict(document.uploaded_by), "uploaded_at": document.uploaded_at.isoformat(), "superseded_at": document.superseded_at})

    _require_inventory_management(access)
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return _validation_response(ValidationError({"file": "A signed agreement file is required."}))
    try:
        content_type = validate_upload(uploaded_file, kinds=DOCUMENT_KINDS, max_bytes=10 * 1024 * 1024)
    except ValidationError as error:
        return _validation_response(error)
    extension = uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else ""
    if extension not in {"pdf", "jpg", "jpeg", "png"}:
        return _validation_response(ValidationError({"file": "Supported signed agreement formats are PDF, JPG, and PNG."}))

    with transaction.atomic():
        superseded = list(AgreementSignedDocument.objects.filter(agreement=agreement, superseded_at__isnull=True))
        AgreementSignedDocument.objects.filter(pk__in=[item.pk for item in superseded]).update(superseded_at=timezone.now())
        if superseded:
            log_bulk_audit(request=request, module="inventory", action="bulk_update", instances=superseded,
                           organization=agreement.organization, project=project,
                           changed_values={"superseded_at": "now"})
        AgreementSignedDocument.objects.create(agreement=agreement, file=uploaded_file, original_filename=uploaded_file.name, content_type=content_type, file_size_bytes=uploaded_file.size, uploaded_by=request.user)
    return Response(agreement_to_dict(_sales_queryset(Agreement, access, project).get(pk=agreement.pk)), status=status.HTTP_201_CREATED)


@crm_endpoint(["POST"], scope="organization")
def agreement_generate_pdf(request, organization_slug, agreement_id):
    """Keep the legacy generate-PDF client action on the approved agreement flow.

    The current SSOT defines signed-copy upload/download, not a second generated
    document format. Returning the agreement metadata keeps the existing client
    action from failing with 404 while leaving signed-copy storage authoritative.
    """
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    agreement = get_object_or_404(_sales_queryset(Agreement, access, project), pk=agreement_id)
    return Response(agreement_to_dict(agreement))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agreement_download_signed(request, organization_slug, agreement_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_permission(access, "plots.export")
    agreement = get_object_or_404(_sales_queryset(Agreement, access, project), pk=agreement_id)
    document = get_object_or_404(AgreementSignedDocument.objects.filter(agreement=agreement, superseded_at__isnull=True).order_by("-uploaded_at", "-id"))
    return private_file_response(document.file, filename=document.original_filename)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agreement_cancel(request, organization_slug, agreement_id): return _legal_transition_view(request, organization_slug, agreement_id, Agreement, transition_agreement, Agreement.Status.CANCELLED, agreement_to_dict)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def registry_schedule(request, organization_slug, registry_id): return _legal_transition_view(request, organization_slug, registry_id, Registry, transition_registry, Registry.Status.SCHEDULED, registry_to_dict)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def registry_complete(request, organization_slug, registry_id): return _legal_transition_view(request, organization_slug, registry_id, Registry, transition_registry, Registry.Status.COMPLETED, registry_to_dict)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def registry_cancel(request, organization_slug, registry_id): return _legal_transition_view(request, organization_slug, registry_id, Registry, transition_registry, Registry.Status.CANCELLED, registry_to_dict)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def possession_schedule(request, organization_slug, possession_id): return _legal_transition_view(request, organization_slug, possession_id, Possession, transition_possession, Possession.Status.SCHEDULED, possession_to_dict)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def possession_complete(request, organization_slug, possession_id): return _legal_transition_view(request, organization_slug, possession_id, Possession, transition_possession, Possession.Status.COMPLETED, possession_to_dict)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def possession_cancel(request, organization_slug, possession_id): return _legal_transition_view(request, organization_slug, possession_id, Possession, transition_possession, Possession.Status.CANCELLED, possession_to_dict)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def installment_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    return _simple_page(request, _sales_queryset(Installment, access, project), installment_to_dict)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agreement_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    return _simple_page(request, _sales_queryset(Agreement, access, project), agreement_to_dict)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def registry_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    return _simple_page(request, _sales_queryset(Registry, access, project), registry_to_dict)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def possession_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    return _simple_page(request, _sales_queryset(Possession, access, project), possession_to_dict)


# Organization-level payment API.  The older inventory/payment routes above
# remain available to existing clients.
def _new_payment_payload(request, organization, project, access):
    rows = request.data.get("booking_allocations") or request.data.get("allocations")
    # Backward-compatible single-booking shape used by older clients.
    if not rows and request.data.get("booking_id"):
        rows = [{"booking_id": request.data.get("booking_id"), "amount": request.data.get("amount"), "installment_id": request.data.get("installment_id"), "registry_charge_id": request.data.get("registry_charge_id")}]
    if not isinstance(rows, list) or not rows: raise ValidationError({"booking_allocations": "Provide at least one allocation."})
    parsed = []
    for row in rows:
        booking = get_object_or_404(_bookings_for_access(access, project), pk=_parse_positive_id(row, "booking_id"))
        installment = None
        charge = None
        if row.get("installment_id"):
            installment = get_object_or_404(_sales_queryset(Installment, access, project), pk=_parse_positive_id(row, "installment_id"))
        if row.get("registry_charge_id"):
            charge = get_object_or_404(
                RegistryCharge.objects.filter(registry__in=_registry_queryset(access, project)).select_related("registry__booking"),
                pk=_parse_positive_id(row, "registry_charge_id"),
            )
        parsed.append({"booking": booking, "installment": installment, "registry_charge": charge, "amount": _decimal(row, "amount")})
    return parsed


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def managed_payments(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if request.method == "POST":
        _require_permission(access, "payments.add")
        try:
            payload = request.data.copy()
            if "amount" not in payload and "payment_amount" in payload: payload["amount"] = payload["payment_amount"]
            if "payment_date" not in payload and "paymentDate" in payload: payload["payment_date"] = payload["paymentDate"]
            if "payment_mode" not in payload and "mode" in payload: payload["payment_mode"] = payload["mode"]
            request._full_data = payload
            payment = create_allocated_payment(organization=access.organization, amount=_decimal(payload, "amount"), payment_method=payload.get("payment_mode") or payload.get("payment_method"), payment_date=_date(payload, "payment_date"), transaction_reference=payload.get("transaction_reference") or payload.get("reference_id"), notes=payload.get("remarks") or payload.get("notes"), user=request.user, allocations=_new_payment_payload(request, access.organization, project, access))
        except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
        return Response(payment_to_dict(_payment_queryset(access, project).get(pk=payment.pk), True), status=status.HTTP_201_CREATED)
    _require_permission(access, "payments.view")
    queryset = _payment_queryset(access, project)
    if value := request.query_params.get("status"): queryset = queryset.filter(status=value)
    if value := request.query_params.get("payment_mode"): queryset = queryset.filter(payment_method=value)
    if value := request.query_params.get("date_from"): queryset = queryset.filter(payment_date__gte=value)
    if value := request.query_params.get("date_to"): queryset = queryset.filter(payment_date__lte=value)
    if value := request.query_params.get("customer"): queryset = queryset.filter(payment_allocations__booking__lead_id=value)
    if value := request.query_params.get("booking"): queryset = queryset.filter(payment_allocations__booking_id=value)
    if value := request.query_params.get("plot"): queryset = queryset.filter(payment_allocations__booking__plot_id=value)
    if value := request.query_params.get("search"): queryset = queryset.filter(Q(payment_id__icontains=value) | Q(transaction_reference__icontains=value) | Q(payment_allocations__booking__lead__first_name__icontains=value) | Q(payment_allocations__booking__lead__last_name__icontains=value) | Q(payment_allocations__booking__plot__plot_number__icontains=value) | Q(receipt__receipt_number__icontains=value)).distinct()
    count, page, page_size, results = _paginate(queryset, request.query_params)
    return Response({"count": count, "next": _page_url(request, page + 1, page_size) if page * page_size < count else None, "previous": _page_url(request, page - 1, page_size) if page > 1 else None, "results": [payment_to_dict(item) for item in results]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def managed_payment_detail(request, organization_slug, payment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.view")
    return Response(payment_to_dict(get_object_or_404(_payment_queryset(access, project), pk=payment_id), True))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def managed_payment_summary(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.view")
    bookings = _bookings_for_access(access, project).filter(status=PlotBooking.Status.CONFIRMED).select_related("plot")
    totals = [payment_totals(booking) for booking in bookings]
    total_dues = sum((item["final_price"] or Decimal("0") for item in totals), Decimal("0"))
    total_paid = sum((item["net_paid"] for item in totals), Decimal("0"))
    payments = _payment_queryset(access, project)
    distribution = {value: payments.filter(status=value).count() for value, _ in Payment.Status.choices}
    last = payments.filter(status__in=[Payment.Status.SUCCESS, Payment.Status.REFUNDED]).first()
    return Response({"total_dues": str(total_dues), "total_paid": str(total_paid), "outstanding": str(max(total_dues - total_paid, Decimal("0"))), "last_payment": payment_to_dict(last) if last else None, "status_distribution": distribution})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def managed_payment_confirm(request, organization_slug, payment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.add"); payment = get_object_or_404(_payment_queryset(access, project), pk=payment_id)
    try: payment = confirm_payment(payment=payment, user=request.user)
    except ValidationError as error: return _validation_response(error)
    return Response(payment_to_dict(_payment_queryset(access, project).get(pk=payment.pk), True))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payment_receipt(request, organization_slug, payment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.view")
    payment = get_object_or_404(_payment_queryset(access, project), pk=payment_id)
    if not hasattr(payment, "receipt"): raise PermissionDenied("A receipt is available after payment confirmation.")
    receipt = payment.receipt
    response = HttpResponse(payment_receipt_pdf(payment, receipt), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{payment_receipt_filename(receipt)}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def managed_payment_refund(request, organization_slug, payment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.add"); payment = get_object_or_404(_payment_queryset(access, project), pk=payment_id)
    try: refund = refund_payment(payment=payment, amount=_decimal(request.data, "amount"), reason=str(request.data.get("reason", "")), refund_date=_date(request.data, "refund_date"), user=request.user)
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response({"id": refund.id, "status": refund.status}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def payment_refund_approve(request, organization_slug, payment_id, refund_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.refund")
    payment = get_object_or_404(_payment_queryset(access, project), pk=payment_id)
    refund = get_object_or_404(PaymentRefund.objects.filter(organization=access.organization, payment=payment), pk=refund_id)
    try: refund = approve_refund(refund=refund, user=request.user)
    except ValidationError as error: return _validation_response(error)
    return Response({"id": refund.id, "status": refund.status})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def managed_payment_adjustment(request, organization_slug, payment_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.adjust")
    payment = get_object_or_404(_payment_queryset(access, project), pk=payment_id)
    try: adjustment = adjust_payment(payment=payment, amount=_decimal(request.data, "amount"), reason=str(request.data.get("reason", "")), user=request.user)
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response({"id": adjustment.id, "payment_id": payment.id, "amount": str(adjustment.amount), "reason": adjustment.reason}, status=status.HTTP_201_CREATED)


def _require_customer_view(access):
    if access.is_platform:
        return
    role = membership_role_code(access.membership)
    if role in {"admin", "manager", "telecaller", "site-visit-executive"}:
        return
    raise PermissionDenied("This role does not have customer visibility.")


def _require_customer_edit(access):
    if access.is_platform or is_organization_admin(access.membership) or membership_role_code(access.membership) == "manager":
        return
    raise PermissionDenied("Only Managers and Admins may edit customers.")


def _require_customer_create(access, project):
    if access.is_platform or has_permission(
        access.membership.user,
        access.organization,
        "customers.add",
        project=project,
    ):
        return
    raise PermissionDenied("This role does not have permission to create customers.")


def _customer_for_access(access, project, customer_id):
    _require_customer_view(access)
    queryset = customer_queryset_for_access(access, project)
    customer = queryset.filter(pk=customer_id).first()
    if customer is None:
        # Legacy payment/site-visit links use the lead id. Resolve that alias
        # without widening the role/project scope of the customer queryset.
        customer = queryset.filter(lead_id=customer_id).first()
    if customer is None:
        raise Http404
    return customer


def _customer_api_payload(request, access, project):
    lead = None
    if request.data.get("lead_id") not in (None, ""):
        lead = get_object_or_404(Lead.objects.filter(organization=access.organization, project=project), pk=request.data.get("lead_id"))
    role = membership_role_code(access.membership)
    if role == "telecaller" and (lead is None or lead.assigned_membership_id != access.membership.id):
        raise PermissionDenied("Telecallers may only create customers for assigned leads.")
    return {
        "organization": access.organization,
        "project": project,
        "lead": lead,
        "full_name": request.data.get("full_name", ""),
        "phone": request.data.get("phone", ""),
        "email": request.data.get("email", ""),
        "address": request.data.get("address", ""),
        "government_id_type": request.data.get("government_id_type", ""),
        "government_id": request.data.get("government_id", ""),
        "actor": request.user,
    }


@crm_endpoint(["GET", "POST"], scope="organization")
def customer_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_customer_view(access)
    if request.method == "POST":
        _require_customer_create(access, project)
        try:
            customer = create_customer(**_customer_api_payload(request, access, project))
        except (ValidationError, ValueError, TypeError) as error:
            response = _validation_response(error)
            if getattr(error, "code", "") == "customer_duplicate":
                response.status_code = status.HTTP_409_CONFLICT
            return response
        return Response(customer_to_dict(customer), status=status.HTTP_201_CREATED)
    query = customer_queryset_for_access(access, project)
    if search := request.query_params.get("search"):
        query = query.filter(
            Q(full_name__icontains=search)
            | Q(customer_code__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )
    if status_value := request.query_params.get("status"):
        if status_value not in Customer.Status.values:
            return Response({"status": "Use a valid customer status."}, status=status.HTTP_400_BAD_REQUEST)
        query = query.filter(status=status_value)
    count, page, page_size, results = _paginate(query.order_by("full_name", "id"), request.query_params)
    return Response({
        "count": count,
        "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
        "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
        "results": [customer_to_dict(customer) for customer in results],
    })


@crm_endpoint(["GET", "PATCH"], scope="organization")
def customer_detail(request, organization_slug, customer_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    customer = _customer_for_access(access, project, customer_id)
    if request.method == "GET":
        return Response(customer_to_dict(customer))
    _require_customer_edit(access)
    updates = {}
    for field in ("full_name", "address"):
        if field in request.data:
            updates[field] = str(request.data[field] or "").strip()
    if "phone" in request.data:
        from .customer_services import normalize_phone
        normalized_phone = normalize_phone(request.data.get("phone")) if request.data.get("phone") else ""
        if request.data.get("phone") and normalized_phone is None:
            return Response({"phone": "Phone number cannot be normalized."}, status=status.HTTP_400_BAD_REQUEST)
        updates["phone"] = normalized_phone
    if "email" in request.data:
        from .customer_services import normalize_customer_email
        updates["email"] = normalize_customer_email(request.data.get("email"))
    identity_changed = any(field in request.data for field in ("phone", "email", "government_id_type", "government_id"))
    if "status" in request.data:
        try:
            customer = set_customer_status(customer, request.data["status"], request.data.get("reason", ""), request.user)
        except (ValidationError, PermissionDenied) as error:
            return _validation_response(error) if isinstance(error, ValidationError) else Response({"detail": str(error)}, status=403)
    if updates or identity_changed:
        if identity_changed:
            try:
                update_customer_identity(
                    customer,
                    phone=request.data.get("phone") if "phone" in request.data else None,
                    email=request.data.get("email") if "email" in request.data else None,
                    government_id_type=request.data.get("government_id_type") if "government_id_type" in request.data else None,
                    government_id=request.data.get("government_id") if "government_id" in request.data else None,
                )
            except (ValidationError, ValueError, TypeError) as error:
                response = _validation_response(error)
                if getattr(error, "code", "") == "customer_duplicate":
                    response.status_code = status.HTTP_409_CONFLICT
                return response
        for field, value in updates.items():
            if field not in {"phone", "email"}:
                setattr(customer, field, value)
        if any(field not in {"phone", "email"} for field in updates):
            customer.save(update_fields=[field for field in updates if field not in {"phone", "email"}] + ["updated_at"])
    return Response(customer_to_dict(customer))


@crm_endpoint(["GET"], scope="organization")
def customer_360(request, organization_slug, customer_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    customer = _customer_for_access(access, project, customer_id)
    data = customer_360_data(customer)
    data["totals"]["total_paid"] = str(data["totals"]["total_paid"])
    data["totals"]["outstanding"] = str(data["totals"]["outstanding"])
    return Response(data)


@crm_endpoint(["POST"], scope="organization")
def customer_notes(request, organization_slug, customer_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    customer = _customer_for_access(access, project, customer_id)
    note_text = str(request.data.get("note_text", "")).strip()
    if not note_text:
        return Response({"note_text": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)
    note = CustomerNote.objects.create(customer=customer, author=request.user, note_text=note_text)
    return Response({"id": note.id, "customer_id": note.customer_id, "author_id": note.author_id, "note_text": note.note_text, "created_at": note.created_at.isoformat()}, status=status.HTTP_201_CREATED)


def customer_payment_history(request, organization_slug, customer_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.view")
    customer = _customer_for_access(access, project, customer_id)
    return _simple_page(request, _payment_queryset(access, project).filter(payment_allocations__booking__customer_id=customer.id).distinct(), payment_to_dict)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def customer_payment_ledger(request, organization_slug, customer_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.view")
    customer = _customer_for_access(access, project, customer_id)
    bookings = _bookings_for_access(access, project).filter(customer=customer, status=PlotBooking.Status.CONFIRMED)
    totals = [payment_totals(item) for item in bookings]
    due = sum((item["final_price"] or Decimal("0") for item in totals), Decimal("0")); paid = sum((item["net_paid"] for item in totals), Decimal("0"))
    payment_entries = _payment_queryset(access, project).filter(
        payment_allocations__booking__customer=customer,
        status__in=[Payment.Status.SUCCESS, Payment.Status.REFUNDED],
    ).distinct().order_by("payment_date", "id")
    running_paid = Decimal("0")
    entries = []
    for payment in payment_entries:
        running_paid += payment.amount
        entries.append({
            "date": payment.payment_date.isoformat(),
            "type": "payment",
            "reference": payment.payment_id,
            "particulars": f"Payment #{payment.payment_id}",
            "credit": str(payment.amount),
            "debit": "0.00",
            "balance": str(max(due - running_paid, Decimal("0"))),
        })
    return Response({"customer": {"id": customer.id, "name": customer.full_name}, "opening_balance": "0.00", "total_dues": str(due), "total_paid": str(paid), "current_outstanding": str(max(due - paid, Decimal("0"))), "entries": entries})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def customer_dues(request, organization_slug, customer_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "payments.view")
    customer = _customer_for_access(access, project, customer_id)
    bookings = _bookings_for_access(access, project).filter(customer=customer, status=PlotBooking.Status.CONFIRMED).select_related("plot", "plot__block").prefetch_related("installments")
    rows = []
    for booking in bookings:
        summary = payment_totals(booking)
        installments = []
        for installment in booking.installments.all():
            paid = InstallmentPayment.objects.filter(installment=installment, payment__status__in=[Payment.Status.SUCCESS, Payment.Status.REFUNDED]).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            paid += PaymentAllocation.objects.filter(installment=installment, payment__status__in=[Payment.Status.SUCCESS, Payment.Status.REFUNDED]).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            installments.append({"id": installment.id, "title": installment.title, "due_date": installment.due_date.isoformat(), "amount": str(installment.amount), "paid_amount": str(paid), "outstanding": str(max(installment.amount - paid, Decimal("0"))), "status": installment.status})
        rows.append({"booking_id": booking.id, "plot": {"id": booking.plot_id, "plot_number": booking.plot.plot_number, "block": booking.plot.block.name}, "total_due": str(summary["final_price"] or Decimal("0")), "paid_amount": str(summary["net_paid"]), "outstanding": str(summary["outstanding_amount"] or Decimal("0")), "installments": installments})
    return Response({"customer": {"id": customer.id, "name": customer.full_name}, "results": rows})


def _registry_queryset(access, project=None):
    queryset = Registry.objects.filter(organization=access.organization)
    if project is not None:
        queryset = queryset.filter(booking__plot__project=project)
    queryset = apply_data_scope(
        queryset,
        access,
        module="registry",
        membership_lookups=("booking__lead__assigned_membership",),
        user_lookups=("booking__created_by", "created_by"),
    )
    return queryset.select_related("booking__lead", "booking__customer", "booking__plot__block", "created_by").prefetch_related("charges", "status_history__changed_by")


def managed_registry_to_dict(item, detailed=False):
    charges = list(item.charges.all())
    total = sum((charge.amount for charge in charges), Decimal("0"))
    paid = PaymentAllocation.objects.filter(registry_charge__registry=item, payment__status__in=[Payment.Status.SUCCESS, Payment.Status.REFUNDED]).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    charge_values = {charge.code: charge.amount for charge in charges}
    customer = item.booking.customer
    data = {"id": item.id, "registry_id": f"REG-{item.id}", "status": item.status, "registry_number": item.registry_number, "registry_date": item.registry_date.isoformat() if item.registry_date else None, "booking_id": item.booking_id, "customer_id": customer.id if customer else None, "buyer_name": customer.full_name if customer else item.booking.lead.full_name, "buyer_mobile": customer.phone if customer else item.booking.lead.phone, "buyer_email": customer.email if customer else item.booking.lead.email, "plot_id": item.booking.plot_id, "plot_number": item.booking.plot.plot_number, "block_name": item.booking.plot.block.name, "consideration_amount": str(item.consideration_amount) if item.consideration_amount is not None else None, "booking": {"id": item.booking_id, "customer": {"id": customer.id if customer else None, "name": customer.full_name if customer else item.booking.lead.full_name}, "plot": {"id": item.booking.plot_id, "plot_number": item.booking.plot.plot_number, "block": item.booking.plot.block.name}}, "charges": {"stamp_duty": str(charge_values.get("stamp_duty", 0)), "registration_charges": str(charge_values.get("registration_charges", 0)), "legal_fees": str(charge_values.get("legal_fees", 0)), "miscellaneous": str(charge_values.get("miscellaneous", 0)), "tds": str(charge_values.get("tds", 0)), "total_charges": str(total), "paid_amount": str(paid), "pending_amount": str(max(total - paid, Decimal("0")))}, "total_charges": str(total), "paid_amount": str(paid), "pending_amount": str(max(total - paid, Decimal("0")))}
    if detailed: data.update({"registry_time": item.registry_time.isoformat() if item.registry_time else None, "sub_registrar_office": item.sub_registrar_office, "document_type": item.document_type, "consideration_amount": str(item.consideration_amount) if item.consideration_amount is not None else None, "agreement_number": item.agreement_number, "agreement_date": item.agreement_date.isoformat() if item.agreement_date else None, "notes": item.notes, "reminder_date": item.reminder_date.isoformat() if item.reminder_date else None, "reminder_enabled": item.reminder_enabled, "charges": [{"id": c.id, "code": c.code, "label": c.label, "calculation_type": c.calculation_type, "calculation_value": str(c.calculation_value), "amount": str(c.amount)} for c in charges], "history": [{"status": h.new_status, "old_status": h.old_status, "remarks": h.remarks, "changed_at": h.changed_at.isoformat(), "actor": _actor_to_dict(h.changed_by)} for h in item.status_history.all()]})
    return data


def registry_document_to_dict(document):
    customer_document = document.customer_document
    return {"id": document.id, "registry_id": document.registry_id, "document_label": document.document_label, "document_type": document.document_type, "source": document.source, "original_filename": document.original_filename or (customer_document.file_name if customer_document else None), "content_type": document.content_type or (customer_document.content_type if customer_document else None), "file_size": document.file_size_bytes or (customer_document.file_size if customer_document else 0), "uploaded_by": _actor_to_dict(document.uploaded_by), "created_at": document.created_at.isoformat(), "download_url": f"/api/organizations/{document.registry.organization.slug}/registries/{document.registry_id}/documents/{document.id}/download/", "customer_document": ({"id": customer_document.id, "document_name": customer_document.document_name, "file_name": customer_document.file_name, "content_type": customer_document.content_type} if customer_document else None)}


def _registry_documents_queryset(access, project, registry_id):
    registry = get_object_or_404(_registry_queryset(access, project), pk=registry_id)
    return registry, RegistryDocument.objects.filter(registry=registry).select_related("customer_document", "uploaded_by", "registry__organization")


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def managed_registry_documents(request, organization_slug, registry_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    registry, queryset = _registry_documents_queryset(access, project, registry_id)
    if request.method == "GET":
        results = [registry_document_to_dict(document) for document in queryset]
        return Response({"count": len(results), "results": results})

    _require_permission(access, "registry.edit")
    customer_document_id = request.data.get("customer_document_id")
    customer_document = None
    uploaded_file = request.FILES.get("file")
    if customer_document_id:
        customer_document = get_object_or_404(
            CustomerDocument.objects.filter(
                organization=access.organization,
                customer=registry.booking.customer,
                customer__project=project,
                pk=customer_document_id,
            )
        )
    elif not uploaded_file:
        return _validation_response(ValidationError({"file": "Attach a file or select an existing customer document."}))
    content_type = ""
    if uploaded_file:
        try:
            content_type = validate_upload(uploaded_file, kinds=DOCUMENT_KINDS, max_bytes=10 * 1024 * 1024)
        except ValidationError as error:
            return _validation_response(error)

    document = RegistryDocument(
        registry=registry,
        customer_document=customer_document,
        file=uploaded_file,
        document_label=str(request.data.get("document_label", "Customer Document" if customer_document else uploaded_file.name)).strip(),
        document_type=str(request.data.get("document_type", "other")).strip() or "other",
        original_filename=uploaded_file.name if uploaded_file else "",
        content_type=content_type,
        file_size_bytes=uploaded_file.size if uploaded_file else 0,
        uploaded_by=request.user,
    )
    try:
        document.full_clean()
        document.save()
    except ValidationError as error:
        return _validation_response(error)
    return Response(registry_document_to_dict(document), status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def managed_registry_document_delete(request, organization_slug, registry_id, document_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    registry, queryset = _registry_documents_queryset(access, project, registry_id)
    _require_permission(access, "registry.edit")
    document = get_object_or_404(queryset, pk=document_id)
    document.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def managed_registry_document_download(request, organization_slug, registry_id, document_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_permission(access, "registry.export")
    _registry, queryset = _registry_documents_queryset(access, project, registry_id)
    document = get_object_or_404(queryset, pk=document_id)
    if document.file:
        return private_file_response(document.file, filename=document.original_filename or os.path.basename(document.file.name))
    if document.customer_document_id:
        return private_file_response(document.customer_document.file, filename=document.customer_document.file_name)
    raise Http404("File not found.")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def managed_registries(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if request.method == "POST":
        _require_permission(access, "registry.add")
        booking = get_object_or_404(_bookings_for_access(access, project), pk=_parse_positive_id(request.data, "booking_id"))
        try:
            item = create_registry(booking=booking, registry_number=str(request.data.get("registry_number", "")).strip(), registry_date=_date(request.data, "registry_date", False), registry_time=request.data.get("registry_time") or None, sub_registrar_office=str(request.data.get("sub_registrar_office", "")), document_type=str(request.data.get("document_type", "")), consideration_amount=_decimal(request.data, "consideration_amount") if request.data.get("consideration_amount") else None, agreement_number=str(request.data.get("agreement_number", "")), agreement_date=_date(request.data, "agreement_date", False), notes=str(request.data.get("notes", "")), reminder_date=_date(request.data, "reminder_date", False), reminder_enabled=bool(request.data.get("reminder_enabled", False)), created_by=request.user)
        except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
        return Response(managed_registry_to_dict(_registry_queryset(access, project).get(pk=item.pk), True), status=status.HTTP_201_CREATED)
    _require_permission(access, "registry.view"); queryset = _registry_queryset(access, project)
    if value := request.query_params.get("status"): queryset = queryset.filter(status=value)
    if value := request.query_params.get("plot"): queryset = queryset.filter(booking__plot_id=value)
    if value := request.query_params.get("block"): queryset = queryset.filter(booking__plot__block_id=value)
    if value := request.query_params.get("customer"): queryset = queryset.filter(booking__lead_id=value)
    if value := request.query_params.get("registry_date_from"): queryset = queryset.filter(registry_date__gte=value)
    if value := request.query_params.get("registry_date_to"): queryset = queryset.filter(registry_date__lte=value)
    if value := request.query_params.get("search"): queryset = queryset.filter(Q(registry_number__icontains=value) | Q(booking__plot__plot_number__icontains=value) | Q(booking__lead__first_name__icontains=value) | Q(booking__lead__last_name__icontains=value) | Q(booking_id__icontains=value))
    count, page, page_size, results = _paginate(queryset, request.query_params)
    return Response({"count": count, "next": _page_url(request, page + 1, page_size) if page * page_size < count else None, "previous": _page_url(request, page - 1, page_size) if page > 1 else None, "results": [managed_registry_to_dict(item) for item in results]})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def managed_registry_detail(request, organization_slug, registry_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); item = get_object_or_404(_registry_queryset(access, project), pk=registry_id)
    if request.method == "GET": _require_permission(access, "registry.view"); return Response(managed_registry_to_dict(item, True))
    _require_permission(access, "registry.edit")
    if "status" in request.data: return _validation_response(ValidationError({"status": "Use the status endpoint."}))
    try:
        for field in ("registry_number", "sub_registrar_office", "document_type", "notes", "reminder_enabled"):
            if field in request.data: setattr(item, field, request.data[field])
        for field in ("registry_date", "agreement_date", "reminder_date"):
            if field in request.data: setattr(item, field, _date(request.data, field, False))
        if "consideration_amount" in request.data: item.consideration_amount = _decimal(request.data, "consideration_amount")
        item.full_clean(); item.save()
    except (ValidationError, ValueError, TypeError) as error: return _validation_response(error)
    return Response(managed_registry_to_dict(_registry_queryset(access, project).get(pk=item.pk), True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def managed_registry_status(request, organization_slug, registry_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "registry.status"); item = get_object_or_404(_registry_queryset(access, project), pk=registry_id)
    target = request.data.get("status")
    try: item = transition_registry(registry=item, status=target, user=request.user, remarks=str(request.data.get("remarks", "")))
    except ValidationError as error: return _validation_response(error)
    return Response(managed_registry_to_dict(_registry_queryset(access, project).get(pk=item.pk), True))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def managed_registry_history(request, organization_slug, registry_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); _require_permission(access, "registry.view")
    item = get_object_or_404(_registry_queryset(access, project), pk=registry_id)
    return Response({"results": [{"action": h.new_status, "old_status": h.old_status, "remarks": h.remarks, "performed_by": _actor_to_dict(h.changed_by), "timestamp": h.changed_at.isoformat()} for h in item.status_history.all()]})
