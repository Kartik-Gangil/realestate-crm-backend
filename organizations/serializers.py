from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Organization, OrganizationMembership, Project


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name", "slug", "code", "status", "is_active", "created_at")
        read_only_fields = ("id", "is_active", "created_at")


class ProjectSerializer(serializers.ModelSerializer):
    organization_id = serializers.PrimaryKeyRelatedField(
        source="organization", queryset=Organization.objects.filter(is_active=True), write_only=True
    )
    organization = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = Project
        fields = (
            "id", "organization", "organization_id", "name", "code", "description",
            "status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_code(self, value):
        return value.strip().upper()


class MembershipSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationMembership
        fields = ("id", "user_id", "email", "name", "role", "organization_role", "is_active", "joined_at")
        read_only_fields = ("organization_role",)

    def get_name(self, obj):
        return obj.user.get_full_name()


class AddMembershipSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=OrganizationMembership.Role.choices)

    def validate_email(self, value):
        try:
            get_user_model().objects.get(email__iexact=value)
        except get_user_model().DoesNotExist:
            raise serializers.ValidationError("No user exists with this email.")
        return value

    def validate(self, attrs):
        attrs["user"] = get_user_model().objects.get(email__iexact=attrs["email"])
        return attrs
