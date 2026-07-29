from django.contrib.auth import get_user_model


class EmailBackend:
    """Authenticates Django users with their email address and password."""

    def authenticate(self, request, email=None, password=None, **kwargs):
        email = email or kwargs.get("username")
        if not email or not password:
            return None
        user_model = get_user_model()
        try:
            user = user_model.objects.get(email__iexact=email)
        except user_model.DoesNotExist:
            return None
        return user if user.check_password(password) and user.is_active else None

    def get_user(self, user_id):
        user_model = get_user_model()
        try:
            return user_model.objects.get(pk=user_id)
        except user_model.DoesNotExist:
            return None