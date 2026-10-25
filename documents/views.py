from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from leads.models import Lead
from organizations.services import apply_data_scope, get_organization_access, get_project_context
from .models import CustomerDocument, CustomerDocumentRequirement, DocumentCategory, EmployeeDocument, EmployeeDocumentCategory
from .permissions import require_document_management, require_document_view
from .serializers import CustomerDocumentSerializer, CustomerDocumentUploadSerializer, DocumentCategorySerializer, DocumentRequirementSerializer, VerificationHistorySerializer
from .services import archive_customer_document, archive_employee_document, get_customer_document_summary, put_document_under_verification, reject_customer_document, upload_customer_document, upload_employee_document, verify_customer_document
from organizations.models import OrganizationActivity, OrganizationMembership
from core.files import private_file_response


def _error(error): return Response(getattr(error, "message_dict", {"detail": error.messages if hasattr(error, "messages") else str(error)}), status=status.HTTP_400_BAD_REQUEST)
def _page(request, queryset, serializer):
    try: page = max(int(request.query_params.get("page", 1)), 1); page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
    except ValueError: raise ValidationError({"page": "Page and page_size must be integers."})
    count = queryset.count(); results = queryset[(page - 1) * page_size:page * page_size]
    return Response({"count": count, "next": None, "previous": None, "results": [serializer(item).data for item in results]})
def _docs(access, project):
    queryset = CustomerDocument.objects.filter(
        organization=access.organization,
        customer__project=project,
    ).select_related("customer", "document_category", "uploaded_by", "verified_by", "rejected_by")
    return apply_data_scope(
        queryset,
        access,
        module="documents",
        membership_lookups=("customer__assigned_membership",),
        user_lookups=("uploaded_by",),
    )


def _customer(access, customer_id, project):
    queryset = Lead.objects.filter(organization=access.organization, project=project)
    queryset = apply_data_scope(queryset, access, module="documents", membership_lookups=("assigned_membership",))
    return get_object_or_404(queryset, pk=customer_id)


def _doc(access, document_id, project): return get_object_or_404(_docs(access, project), pk=document_id)

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def document_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if request.method == "POST":
        require_document_management(access); serializer = CustomerDocumentUploadSerializer(data=request.data); serializer.is_valid(raise_exception=True); data = serializer.validated_data
        try:
            document = upload_customer_document(organization=access.organization, customer=_customer(access, data["customer"], project), document_category=get_object_or_404(DocumentCategory.objects.filter(organization=access.organization), pk=data["document_category"]), uploaded_file=data["file"], document_name=data["document_name"], expiry_date=data.get("expiry_date"), notes=data.get("notes", ""), user=request.user)
        except ValidationError as error: return _error(error)
        return Response(CustomerDocumentSerializer(_docs(access, project).get(pk=document.pk)).data, status=status.HTTP_201_CREATED)
    require_document_view(access)
    query = _docs(access, project)
    if q := request.query_params.get("search"): query = query.filter(Q(document_name__icontains=q) | Q(file_name__icontains=q) | Q(customer__first_name__icontains=q) | Q(customer__last_name__icontains=q) | Q(document_category__name__icontains=q))
    for key, field in (("customer", "customer_id"), ("category", "document_category_id"), ("status", "status")):
        if value := request.query_params.get(key): query = query.filter(**{field: value})
    if "active" in request.query_params: query = query.filter(is_active=request.query_params["active"].lower() == "true")
    return _page(request, query, CustomerDocumentSerializer)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_detail(request, organization_slug, document_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    require_document_view(access)
    return Response(CustomerDocumentSerializer(_doc(access, document_id, project)).data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_download(request, organization_slug, document_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    require_document_view(access)
    document = _doc(access, document_id, project)
    return private_file_response(document.file, filename=document.file_name)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_history(request, organization_slug, document_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    require_document_view(access)
    document = _doc(access, document_id, project)
    versions = _docs(access, project).filter(customer=document.customer, document_category=document.document_category).order_by("-version")
    return Response({"versions": CustomerDocumentSerializer(versions, many=True).data, "verification_history": VerificationHistorySerializer(document.verification_history.select_related("changed_by"), many=True).data})

def _action(request, slug, document_id, action):
    access = get_organization_access(request.user, slug); project = get_project_context(request, access); require_document_management(access); doc = _doc(access, document_id, project)
    try:
        if action == "under-verification": doc = put_document_under_verification(document=doc, user=request.user)
        elif action == "verify": doc = verify_customer_document(document=doc, user=request.user)
        elif action == "reject": doc = reject_customer_document(document=doc, user=request.user, reason=str(request.data.get("rejection_reason", "")))
        else: doc = archive_customer_document(document=doc, user=request.user)
    except ValidationError as error: return _error(error)
    return Response(CustomerDocumentSerializer(_docs(access, project).get(pk=doc.pk)).data)
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
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); customer = _customer(access, customer_id, project)
    require_document_view(access)
    requirements = CustomerDocumentRequirement.objects.filter(organization=access.organization, customer=customer).select_related("document_category")
    return Response({"customer": {"id": customer.id, "full_name": customer.full_name}, "requirements": DocumentRequirementSerializer(requirements, many=True).data, "documents": CustomerDocumentSerializer(_docs(access, project).filter(customer=customer, is_active=True), many=True).data, "summary": get_customer_document_summary(customer)})

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def categories(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    if request.method == "GET":
        require_document_view(access)
        return Response(DocumentCategorySerializer(DocumentCategory.objects.filter(organization=access.organization), many=True).data)
    require_document_management(access); serializer = DocumentCategorySerializer(data=request.data); serializer.is_valid(raise_exception=True); category = serializer.save(organization=access.organization); return Response(DocumentCategorySerializer(category).data, status=201)
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def category_detail(request, organization_slug, category_id):
    access = get_organization_access(request.user, organization_slug); require_document_management(access); category = get_object_or_404(DocumentCategory.objects.filter(organization=access.organization), pk=category_id); serializer = DocumentCategorySerializer(category, data=request.data, partial=True); serializer.is_valid(raise_exception=True); return Response(DocumentCategorySerializer(serializer.save()).data)

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def requirements(request, organization_slug, customer_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); customer = _customer(access, customer_id, project); query = CustomerDocumentRequirement.objects.filter(organization=access.organization, customer=customer).select_related("document_category")
    if request.method == "GET":
        require_document_view(access)
        return Response(DocumentRequirementSerializer(query, many=True).data)
    require_document_management(access); serializer = DocumentRequirementSerializer(data=request.data); serializer.is_valid(raise_exception=True); category = serializer.validated_data["document_category"]
    if category.organization_id != access.organization.id: return Response({"document_category": "Use a category in this organization."}, status=400)
    requirement = CustomerDocumentRequirement.objects.create(organization=access.organization, customer=customer, **serializer.validated_data); return Response(DocumentRequirementSerializer(requirement).data, status=201)
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def requirement_detail(request, organization_slug, customer_id, requirement_id):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); require_document_management(access); customer = _customer(access, customer_id, project); obj = get_object_or_404(CustomerDocumentRequirement.objects.filter(organization=access.organization, customer=customer), pk=requirement_id); serializer = DocumentRequirementSerializer(obj, data=request.data, partial=True); serializer.is_valid(raise_exception=True)
    if "document_category" in serializer.validated_data and serializer.validated_data["document_category"].organization_id != access.organization.id: return Response({"document_category": "Use a category in this organization."}, status=400)
    return Response(DocumentRequirementSerializer(serializer.save()).data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pending_verification(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access); require_document_view(access); return _page(request, _docs(access, project).filter(is_active=True, status__in=[CustomerDocument.Status.UPLOADED, CustomerDocument.Status.UNDER_VERIFICATION]), CustomerDocumentSerializer)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def expiry_alerts(request, organization_slug):
    access = get_organization_access(request.user, organization_slug); project = get_project_context(request, access)
    require_document_view(access)
    today = timezone.localdate(); 
    soon = today + timedelta(days=getattr(settings, "DOCUMENT_EXPIRY_WARNING_DAYS", 30)); 
    state = request.query_params.get("state", "expired"); 
    query = _docs(access, project).filter(is_active=True)
    query = query.filter(expiry_date__lt=today) if state == "expired" else query.filter(expiry_date__gte=today, expiry_date__lte=soon)
    return _page(request, query, CustomerDocumentSerializer)


def _employee_document(access, document_id):
    queryset = EmployeeDocument.objects.filter(organization=access.organization).select_related("employee__user", "document_category", "uploaded_by")
    queryset = apply_data_scope(queryset, access, module="documents", membership_lookups=("employee",), user_lookups=("uploaded_by",))
    return get_object_or_404(queryset, pk=document_id)


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
    employee = get_object_or_404(
        apply_data_scope(
            OrganizationMembership.objects.filter(organization=access.organization),
            access,
            module="documents",
            membership_lookups=("pk",),
        ),
        pk=employee_id,
    )
    docs = EmployeeDocument.objects.filter(organization=access.organization, employee=employee).select_related("employee__user", "document_category", "uploaded_by")
    if request.method == "GET":
        require_document_view(access)
        return _page(request, docs, lambda obj: type("S", (), {"data": _employee_document_data(obj)})())
    require_document_management(access)
    category = get_object_or_404(EmployeeDocumentCategory.objects.filter(organization=access.organization, is_active=True), pk=request.data.get("document_category"))
    try:
        document = upload_employee_document(organization=access.organization, employee=employee, document_category=category, uploaded_file=request.data.get("file"), document_name=str(request.data.get("document_name", "")), expiry_date=request.data.get("expiry_date") or None, user=request.user)
    except ValidationError as error: return _error(error)
    OrganizationActivity.objects.create(organization=access.organization, employee=employee, action="employee_document_uploaded", module="documents", details={"document_id": document.id, "category": category.code}, performed_by=request.user)
    return Response(_employee_document_data(_employee_document(access, document.pk)), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_document_detail(request, organization_slug, document_id):
    access = get_organization_access(request.user, organization_slug); require_document_view(access)
    return Response(_employee_document_data(_employee_document(access, document_id)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_document_download(request, organization_slug, document_id):
    access = get_organization_access(request.user, organization_slug); require_document_view(access)
    document = _employee_document(access, document_id)
    return private_file_response(document.file, filename=document.file_name)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_document_history(request, organization_slug, document_id):
    access = get_organization_access(request.user, organization_slug); require_document_view(access); document = _employee_document(access, document_id)
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
