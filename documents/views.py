from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from leads.models import Lead
from organizations.services import get_organization_access
from .models import CustomerDocument, CustomerDocumentRequirement, DocumentCategory, EmployeeDocument, EmployeeDocumentCategory, EkycVerification
from .permissions import require_document_management
from .serializers import CustomerDocumentSerializer, CustomerDocumentUploadSerializer, DocumentCategorySerializer, DocumentRequirementSerializer, VerificationHistorySerializer
from .services import archive_customer_document, archive_employee_document, create_expiry_notifications, get_customer_document_summary, put_document_under_verification, reject_customer_document, upload_customer_document, upload_employee_document, verify_customer_document, verify_ekyc as run_ekyc
from .security import decrypt_bytes
from organizations.models import OrganizationActivity, OrganizationMembership


def _error(error): return Response(getattr(error, "message_dict", {"detail": error.messages if hasattr(error, "messages") else str(error)}), status=status.HTTP_400_BAD_REQUEST)
def _page(request, queryset, serializer):
    try: page = max(int(request.query_params.get("page", 1)), 1); page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
    except ValueError: raise ValidationError({"page": "Page and page_size must be integers."})
    count = queryset.count(); results = queryset[(page - 1) * page_size:page * page_size]
    return Response({"count": count, "next": None, "previous": None, "results": [serializer(item).data for item in results]})
def _docs(access): return CustomerDocument.objects.filter(organization=access.organization).select_related("customer", "document_category", "uploaded_by", "verified_by", "rejected_by")
def _customer(access, customer_id): return get_object_or_404(Lead.objects.filter(organization=access.organization), pk=customer_id)
def _doc(access, document_id): return get_object_or_404(_docs(access), pk=document_id)

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def document_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    if request.method == "POST":
        require_document_management(access); serializer = CustomerDocumentUploadSerializer(data=request.data); serializer.is_valid(raise_exception=True); data = serializer.validated_data
        try:
            document = upload_customer_document(organization=access.organization, customer=_customer(access, data["customer"]), document_category=get_object_or_404(DocumentCategory.objects.filter(organization=access.organization), pk=data["document_category"]), uploaded_file=data["file"], document_name=data["document_name"], expiry_date=data.get("expiry_date"), notes=data.get("notes", ""), user=request.user)
        except ValidationError as error: return _error(error)
        return Response(CustomerDocumentSerializer(_docs(access).get(pk=document.pk)).data, status=status.HTTP_201_CREATED)
    query = _docs(access)
    if q := request.query_params.get("search"): query = query.filter(Q(document_name__icontains=q) | Q(file_name__icontains=q) | Q(customer__first_name__icontains=q) | Q(customer__last_name__icontains=q) | Q(document_category__name__icontains=q))
    for key, field in (("customer", "customer_id"), ("category", "document_category_id"), ("status", "status")):
        if value := request.query_params.get(key): query = query.filter(**{field: value})
    if "active" in request.query_params: query = query.filter(is_active=request.query_params["active"].lower() == "true")
    return _page(request, query, CustomerDocumentSerializer)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_detail(request, organization_slug, document_id): return Response(CustomerDocumentSerializer(_doc(get_organization_access(request.user, organization_slug), document_id)).data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_download(request, organization_slug, document_id):
    document = _doc(get_organization_access(request.user, organization_slug), document_id)
    with document.file.open("rb") as stored:
        content = stored.read()
    return HttpResponse(decrypt_bytes(content), content_type=document.content_type, headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'})

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_history(request, organization_slug, document_id):
    document = _doc(get_organization_access(request.user, organization_slug), document_id)
    versions = _docs(get_organization_access(request.user, organization_slug)).filter(customer=document.customer, document_category=document.document_category).order_by("-version")
    return Response({"versions": CustomerDocumentSerializer(versions, many=True).data, "verification_history": VerificationHistorySerializer(document.verification_history.select_related("changed_by"), many=True).data})

def _action(request, slug, document_id, action):
    access = get_organization_access(request.user, slug); require_document_management(access); doc = _doc(access, document_id)
    try:
        if action == "under-verification": doc = put_document_under_verification(document=doc, user=request.user)
        elif action == "verify": doc = verify_customer_document(document=doc, user=request.user)
        elif action == "reject": doc = reject_customer_document(document=doc, user=request.user, reason=str(request.data.get("rejection_reason", "")))
        else: doc = archive_customer_document(document=doc, user=request.user)
    except ValidationError as error: return _error(error)
    return Response(CustomerDocumentSerializer(_docs(access).get(pk=doc.pk)).data)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def document_under_verification(request, organization_slug, document_id): return _action(request, organization_slug, document_id, "under-verification")
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def document_verify(request, organization_slug, document_id): return _action(request, organization_slug, document_id, "verify")
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def document_reject(request, organization_slug, document_id): return _action(request, organization_slug, document_id, "reject")
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def document_archive(request, organization_slug, document_id): return _action(request, organization_slug, document_id, "archive")

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def customer_documents(request, organization_slug, customer_id):
    access = get_organization_access(request.user, organization_slug); customer = _customer(access, customer_id)
    requirements = CustomerDocumentRequirement.objects.filter(organization=access.organization, customer=customer).select_related("document_category")

    from inventory.models import PlotBooking, RegistryDocument
    bookings = PlotBooking.objects.filter(
        organization=access.organization, lead=customer,
        status__in=[PlotBooking.Status.PENDING, PlotBooking.Status.CONFIRMED],
    ).select_related("plot", "plot__block")

    booked_plots = []
    for booking in bookings:
        plot_data = {
            "booking_id": booking.id,
            "plot": {"id": booking.plot_id, "plot_number": booking.plot.plot_number, "block": booking.plot.block.name},
            "status": booking.status,
            "registry": None,
        }
        if hasattr(booking, "registry"):
            registry = booking.registry
            registry_docs = RegistryDocument.objects.filter(registry=registry).select_related("customer_document", "uploaded_by")
            plot_data["registry"] = {
                "id": registry.id,
                "status": registry.status,
                "documents": [
                    {
                        "id": d.id,
                        "document_label": d.document_label,
                        "document_type": d.document_type,
                        "source": "reference" if d.customer_document_id else "upload",
                        "customer_document_id": d.customer_document_id,
                        "file_name": d.file_name or (d.customer_document.file_name if d.customer_document_id else None),
                        "uploaded_by": {"id": d.uploaded_by_id, "name": d.uploaded_by.get_full_name()} if d.uploaded_by_id else None,
                        "created_at": d.created_at.isoformat(),
                    }
                    for d in registry_docs
                ],
            }
        booked_plots.append(plot_data)

    return Response({
        "customer": {"id": customer.id, "full_name": customer.full_name},
        "requirements": DocumentRequirementSerializer(requirements, many=True).data,
        "documents": CustomerDocumentSerializer(_docs(access).filter(customer=customer, is_active=True), many=True).data,
        "summary": get_customer_document_summary(customer),
        "booked_plots": booked_plots,
    })

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def categories(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    if request.method == "GET": return Response(DocumentCategorySerializer(DocumentCategory.objects.filter(organization=access.organization), many=True).data)
    require_document_management(access); serializer = DocumentCategorySerializer(data=request.data); serializer.is_valid(raise_exception=True); category = serializer.save(organization=access.organization); return Response(DocumentCategorySerializer(category).data, status=201)
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def category_detail(request, organization_slug, category_id):
    access = get_organization_access(request.user, organization_slug); require_document_management(access); category = get_object_or_404(DocumentCategory.objects.filter(organization=access.organization), pk=category_id); serializer = DocumentCategorySerializer(category, data=request.data, partial=True); serializer.is_valid(raise_exception=True); return Response(DocumentCategorySerializer(serializer.save()).data)

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def requirements(request, organization_slug, customer_id):
    access = get_organization_access(request.user, organization_slug); customer = _customer(access, customer_id); query = CustomerDocumentRequirement.objects.filter(organization=access.organization, customer=customer).select_related("document_category")
    if request.method == "GET": return Response(DocumentRequirementSerializer(query, many=True).data)
    require_document_management(access); serializer = DocumentRequirementSerializer(data=request.data); serializer.is_valid(raise_exception=True); category = serializer.validated_data["document_category"]
    if category.organization_id != access.organization.id: return Response({"document_category": "Use a category in this organization."}, status=400)
    requirement = CustomerDocumentRequirement.objects.create(organization=access.organization, customer=customer, **serializer.validated_data); return Response(DocumentRequirementSerializer(requirement).data, status=201)
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def requirement_detail(request, organization_slug, customer_id, requirement_id):
    access = get_organization_access(request.user, organization_slug); require_document_management(access); customer = _customer(access, customer_id); obj = get_object_or_404(CustomerDocumentRequirement.objects.filter(organization=access.organization, customer=customer), pk=requirement_id); serializer = DocumentRequirementSerializer(obj, data=request.data, partial=True); serializer.is_valid(raise_exception=True)
    if "document_category" in serializer.validated_data and serializer.validated_data["document_category"].organization_id != access.organization.id: return Response({"document_category": "Use a category in this organization."}, status=400)
    return Response(DocumentRequirementSerializer(serializer.save()).data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pending_verification(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); return _page(request, _docs(access).filter(is_active=True, status__in=[CustomerDocument.Status.UPLOADED, CustomerDocument.Status.UNDER_VERIFICATION]), CustomerDocumentSerializer)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def expiry_alerts(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); 
    create_expiry_notifications()
    today = timezone.localdate(); 
    soon = today + timedelta(days=getattr(settings, "DOCUMENT_EXPIRY_WARNING_DAYS", 30)); 
    state = request.query_params.get("state", "expired"); 
    query = _docs(access).filter(is_active=True)
    query = query.filter(expiry_date__lt=today) if state == "expired" else query.filter(expiry_date__gte=today, expiry_date__lte=soon)
    return _page(request, query, CustomerDocumentSerializer)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify_ekyc(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    require_document_management(access)
    if access.membership and access.membership.role == OrganizationMembership.Role.TELECALLER:
        return Response({"detail": "Only managers and admins can run eKYC."}, status=status.HTTP_403_FORBIDDEN)
    customer = _customer(access, request.data.get("customer"))
    try:
        verification = run_ekyc(customer=customer, provider=request.data.get("provider", "mock"), id_number=request.data.get("id_number", ""), checks=request.data.get("checks", {}), actor=request.user)
    except ValidationError as error:
        return _error(error)
    return Response({"id": verification.id, "status": verification.verification_status, "attempts": verification.attempts}, status=202 if verification.verification_status == EkycVerification.Status.PENDING else 200)


def _employee_document(access, document_id):
    return get_object_or_404(EmployeeDocument.objects.filter(organization=access.organization).select_related("employee__user", "document_category", "uploaded_by"), pk=document_id)


def _employee_document_data(document):
    return {"id": document.id, "employee": {"id": document.employee_id, "employee_id": document.employee.employee_id},
            "document_category": {"id": document.document_category_id, "name": document.document_category.name, "code": document.document_category.code},
            "document_name": document.document_name, "file_name": document.file_name, "file_size": document.file_size,
            "content_type": document.content_type, "version": document.version, "status": document.status,
            "is_active": document.is_active, "expiry_date": document.expiry_date, "uploaded_at": document.uploaded_at}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def employee_documents(request, organization_slug, employee_id):
    access = get_organization_access(request.user, organization_slug)
    employee = get_object_or_404(OrganizationMembership.objects.filter(organization=access.organization), pk=employee_id)
    docs = EmployeeDocument.objects.filter(organization=access.organization, employee=employee).select_related("employee__user", "document_category", "uploaded_by")
    if request.method == "GET": return _page(request, docs, lambda obj: type("S", (), {"data": _employee_document_data(obj)})())
    require_document_management(access)
    category = get_object_or_404(EmployeeDocumentCategory.objects.filter(organization=access.organization, is_active=True), pk=request.data.get("document_category"))
    try:
        document = upload_employee_document(organization=access.organization, employee=employee, document_category=category, uploaded_file=request.data.get("file"), document_name=str(request.data.get("document_name", "")), expiry_date=request.data.get("expiry_date") or None, user=request.user)
    except ValidationError as error: return _error(error)
    OrganizationActivity.objects.create(organization=access.organization, employee=employee, action="employee_document_uploaded", module="documents", details={"document_id": document.id, "category": category.code}, performed_by=request.user)
    return Response(_employee_document_data(_employee_document(access, document.pk)), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_document_detail(request, organization_slug, document_id): return Response(_employee_document_data(_employee_document(get_organization_access(request.user, organization_slug), document_id)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_document_download(request, organization_slug, document_id):
    document = _employee_document(get_organization_access(request.user, organization_slug), document_id)
    return FileResponse(document.file.open("rb"), as_attachment=True, filename=document.file_name, content_type=document.content_type)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_document_history(request, organization_slug, document_id):
    access = get_organization_access(request.user, organization_slug); document = _employee_document(access, document_id)
    versions = EmployeeDocument.objects.filter(organization=access.organization, employee=document.employee, document_category=document.document_category).select_related("employee__user", "document_category", "uploaded_by").order_by("-version")
    return Response({"versions": [_employee_document_data(item) for item in versions]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def employee_document_archive(request, organization_slug, document_id):
    access = get_organization_access(request.user, organization_slug); require_document_management(access); document = _employee_document(access, document_id)
    try: document = archive_employee_document(document=document)
    except ValidationError as error: return _error(error)
    OrganizationActivity.objects.create(organization=access.organization, employee=document.employee, action="employee_document_archived", module="documents", details={"document_id": document.id}, performed_by=request.user)
    return Response(_employee_document_data(_employee_document(access, document.pk)))
