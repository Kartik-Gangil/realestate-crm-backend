from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed

from organizations.services import membership_permission_codes

from .security import AccountLocked, InvalidCredentials, authenticate_with_lockout
from .security import is_developer


class UserSerializer(serializers.ModelSerializer):
    organization_memberships = serializers.SerializerMethodField()
    is_developer = serializers.SerializerMethodField()
    is_platform_admin = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = ("id", "email", "first_name", "last_name", "last_login", "is_active", "is_staff", "is_superuser", "is_developer", "is_platform_admin", "date_joined", "organization_memberships")

    def get_is_developer(self, user):
        return is_developer(user)

    def get_is_platform_admin(self, user):
        return bool(user.groups.filter(name="Platform Admin").exists())


    def get_organization_memberships(self, user):
        memberships = user.organization_memberships.filter(is_active=True).select_related("organization")
        return [
            {
                "id": membership.id,
                "organization": membership.organization.slug,
                "organization_name": membership.organization.name,
                "role": membership.role,
                "role_name": membership.organization_role.name if membership.organization_role_id else membership.role,
                "permissions": [f"{module}.{action}" for module, action in membership_permission_codes(membership)],
            }
            for membership in memberships
        ]

class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(required=False, allow_blank=True)
    identifier = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        identifier = attrs.get("identifier") or attrs.get("email")
        if not identifier:
            raise serializers.ValidationError({"identifier": "Email or phone is required."})
        try:
            user = authenticate_with_lockout(identifier, attrs["password"])
        except AccountLocked:
            raise
        except InvalidCredentials:
            raise AuthenticationFailed("Incorrect email or password.", code="invalid_credentials")
        attrs["user"] = user
        return attrs


class OtpRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
