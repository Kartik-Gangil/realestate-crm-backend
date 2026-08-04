from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Organization, OrganizationMembership, TAB_PERMISSIONS


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name", "slug", "is_active", "created_at")
        read_only_fields = ("id", "is_active", "created_at")


class MembershipSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationMembership
        fields = ("id", "user_id", "email", "name", "role", "is_active", "tab_permissions", "joined_at")

    def get_name(self, obj):
        return obj.user.get_full_name()


class AddMembershipSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=OrganizationMembership.Role.choices)
    tab_permissions = serializers.ListField(child=serializers.ChoiceField(choices=TAB_PERMISSIONS), required=False)

    def validate_tab_permissions(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Each tab can be selected only once.")
        return value
    def validate_email(self, value):
        try:
            self.user = get_user_model().objects.get(email__iexact=value)
        except get_user_model().DoesNotExist:
            raise serializers.ValidationError("No user exists with this email.")
        return value
class TabPermissionsSerializer(serializers.Serializer):
    tab_permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=TAB_PERMISSIONS),
        allow_empty=True,
    )

    def validate_tab_permissions(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Each tab can be selected only once.")
        return value