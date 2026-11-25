from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Department, OrganizationMembership, normalize_mobile_number
from core.files import validate_image_upload


EMPLOYEE_PROFILE_FIELDS = {
    "first_name", "last_name", "profile_photo", "mobile_number", "address",
    "date_of_birth", "gender", "department", "designation", "reporting_manager",
    "date_of_joining", "employment_type", "salary", "work_location", "access_scope",
    "custom_scope_memberships", "project_ids",
}


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ("id", "name", "description", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class EmployeeCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    temporary_password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False, required=False)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=OrganizationMembership.Role.choices, required=False, default=OrganizationMembership.Role.TELECALLER)
    role_id = serializers.IntegerField(required=False, min_value=1)
    profile_photo = serializers.FileField(required=False, allow_null=True, validators=[validate_image_upload])
    mobile_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(max_length=32, required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    designation = serializers.CharField(max_length=150, required=False, allow_blank=True)
    reporting_manager = serializers.IntegerField(required=False, allow_null=True)
    date_of_joining = serializers.DateField(required=False, allow_null=True)
    employment_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    salary = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=0)
    work_location = serializers.CharField(max_length=150, required=False, allow_blank=True)
    shift_start_time = serializers.TimeField(required=False, allow_null=True)
    shift_end_time = serializers.TimeField(required=False, allow_null=True)
    access_scope = serializers.ChoiceField(choices=OrganizationMembership.AccessScope.choices, default=OrganizationMembership.AccessScope.OWN)
    custom_scope_memberships = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)
    custom_scope_departments = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)
    project_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)

    def validate_email(self, value):
        return value.lower()

    def validate_mobile_number(self, value):
        try:
            return normalize_mobile_number(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error

    def validate(self, attrs):
        organization = self.context["organization"]
        user = get_user_model().objects.filter(email__iexact=attrs["email"]).first()
        if user is None and not attrs.get("temporary_password"):
            raise serializers.ValidationError({"temporary_password": "This field is required for a new user account."})
        if user and OrganizationMembership.objects.filter(organization=organization, user=user).exists():
            raise serializers.ValidationError({"email": "This user is already an employee in this organization."})
        mobile_number = attrs.get("mobile_number", "")
        if mobile_number and OrganizationMembership.objects.filter(
            organization=organization, mobile_number=mobile_number
        ).exists():
            raise serializers.ValidationError(
                {"mobile_number": "An employee with this mobile number already exists in this organization."}
            )
        attrs["user"] = user
        return attrs


class EmployeeUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    profile_photo = serializers.FileField(required=False, allow_null=True, validators=[validate_image_upload])
    mobile_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(max_length=32, required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    designation = serializers.CharField(max_length=150, required=False, allow_blank=True)
    reporting_manager = serializers.IntegerField(required=False, allow_null=True)
    date_of_joining = serializers.DateField(required=False, allow_null=True)
    employment_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    salary = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=0)
    work_location = serializers.CharField(max_length=150, required=False, allow_blank=True)
    shift_start_time = serializers.TimeField(required=False, allow_null=True)
    shift_end_time = serializers.TimeField(required=False, allow_null=True)
    email = serializers.EmailField(required=False)
    role = serializers.ChoiceField(choices=OrganizationMembership.Role.choices, required=False)
    role_id = serializers.IntegerField(required=False, min_value=1)
    access_scope = serializers.ChoiceField(choices=OrganizationMembership.AccessScope.choices, required=False)
    custom_scope_memberships = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)
    custom_scope_departments = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)
    project_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)

    def validate_mobile_number(self, value):
        try:
            return normalize_mobile_number(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error

    def validate(self, attrs):
        mobile_number = attrs.get("mobile_number", "")
        organization = self.context.get("organization")
        employee = self.context.get("employee")
        if mobile_number and organization and OrganizationMembership.objects.filter(
            organization=organization, mobile_number=mobile_number
        ).exclude(pk=employee.pk if employee else None).exists():
            raise serializers.ValidationError(
                {"mobile_number": "An employee with this mobile number already exists in this organization."}
            )
        return attrs
