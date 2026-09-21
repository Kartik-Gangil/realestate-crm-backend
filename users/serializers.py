from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers

from organizations.services import membership_permission_codes

from .security import AccountLocked, clear_failed_logins, locked_account_remaining, record_failed_login


class UserSerializer(serializers.ModelSerializer):
    organization_memberships = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = ("id", "email", "first_name", "last_name", "last_login", "is_active", "is_staff", "is_superuser", "date_joined", "organization_memberships")
        read_only_fields = ("id", "email", "last_login", "is_active", "is_staff", "is_superuser", "date_joined", "organization_memberships")


    def get_organization_memberships(self, user):
        memberships = user.organization_memberships.filter(is_active=True).select_related("organization")
        return [
            {
                "id": membership.id,
                "organization": membership.organization.slug,
                "organization_name": membership.organization.name,
                "role": membership.role,
                "permissions": [f"{module}.{action}" for module, action in membership_permission_codes(membership)],
            }
            for membership in memberships
        ]

class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)

    def validate_email(self, value):
        if get_user_model().objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def create(self, validated_data):
        email = validated_data.pop("email")
        password = validated_data.pop("password")
        return get_user_model().objects.create_user(username=email, email=email, password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        remaining = locked_account_remaining(attrs["email"])
        if remaining:
            raise AccountLocked(remaining)
        user = authenticate(request=self.context.get("request"), email=attrs["email"], password=attrs["password"])
        if user is None:
            remaining = record_failed_login(attrs["email"])
            if remaining:
                raise AccountLocked(remaining)
            raise serializers.ValidationError({"detail": "Invalid email or password."})
        clear_failed_logins(attrs["email"])
        attrs["user"] = user
        return attrs
