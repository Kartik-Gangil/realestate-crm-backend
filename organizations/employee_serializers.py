from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Department, OrganizationMembership
from .models import Project


EMPLOYEE_PROFILE_FIELDS = {
    "first_name", "last_name", "profile_photo", "mobile_number", "address",
    "date_of_birth", "gender", "department", "designation", "reporting_manager",
    "date_of_joining", "employment_type", "salary", "work_location", "access_scope",
    "custom_scope_memberships",
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
    role = serializers.ChoiceField(choices=OrganizationMembership.Role.choices, default=OrganizationMembership.Role.TELECALLER)
    profile_photo = serializers.FileField(required=False, allow_null=True)
    mobile_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(max_length=32, required=False, allow_blank=True)
    department = serializers.IntegerField(required=False, allow_null=True)
    designation = serializers.CharField(max_length=150, required=False, allow_blank=True)
    reporting_manager = serializers.IntegerField(required=False, allow_null=True)
    date_of_joining = serializers.DateField(required=False, allow_null=True)
    employment_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    salary = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=0)
    work_location = serializers.CharField(max_length=150, required=False, allow_blank=True)
    access_scope = serializers.ChoiceField(choices=OrganizationMembership.AccessScope.choices, default=OrganizationMembership.AccessScope.ALL)
    custom_scope_memberships = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)
    custom_scope_departments = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)
    project_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)

    def validate_email(self, value):
        return value.lower()

    def validate(self, attrs):
        organization = self.context["organization"]
        department_id = attrs.get("department")
        if department_id is not None and not organization.departments.filter(pk=department_id).exists():
            raise serializers.ValidationError({"department": "Use a department in this organization."})
        project_ids = attrs.get("project_ids", [])
        if len(project_ids) != len(set(project_ids)):
            raise serializers.ValidationError({"project_ids": "Project IDs must not contain duplicates."})
        if len(Project.objects.filter(organization=organization, id__in=project_ids)) != len(project_ids):
            raise serializers.ValidationError({"project_ids": "Use projects in this organization."})
        user = get_user_model().objects.filter(email__iexact=attrs["email"]).first()
        if user is None and not attrs.get("temporary_password"):
            raise serializers.ValidationError({"temporary_password": "This field is required for a new user account."})
        if user and OrganizationMembership.objects.filter(organization=organization, user=user).exists():
            raise serializers.ValidationError({"email": "This user is already an employee in this organization."})
        attrs["user"] = user
        return attrs


class EmployeeUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    profile_photo = serializers.FileField(required=False, allow_null=True)
    mobile_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(max_length=32, required=False, allow_blank=True)
    department = serializers.IntegerField(required=False, allow_null=True)
    designation = serializers.CharField(max_length=150, required=False, allow_blank=True)
    reporting_manager = serializers.IntegerField(required=False, allow_null=True)
    date_of_joining = serializers.DateField(required=False, allow_null=True)
    employment_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    salary = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=0)
    work_location = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=OrganizationMembership.Role.choices, required=False)
    access_scope = serializers.ChoiceField(choices=OrganizationMembership.AccessScope.choices, required=False)
    custom_scope_memberships = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)
    custom_scope_departments = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)
    project_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True)

    def validate_department(self, value):
        organization = self.context.get("organization")
        if value is not None and organization and not organization.departments.filter(pk=value).exists():
            raise serializers.ValidationError("Use a department in this organization.")
        return value

    def validate_project_ids(self, value):
        organization = self.context.get("organization")
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Project IDs must not contain duplicates.")
        if len(Project.objects.filter(organization=organization, id__in=value)) != len(value):
            raise serializers.ValidationError("Use projects in this organization.")
        return value
