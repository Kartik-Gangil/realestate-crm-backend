import hashlib

from django.db import migrations
from django.utils import timezone


def _token_hash(token_key):
    return hashlib.sha256(token_key.encode("utf-8")).hexdigest()


def delete_stale_tokens(apps, schema_editor):
    Token = apps.get_model("authtoken", "Token")
    UserSession = apps.get_model("users", "UserSession")
    now = timezone.now()
    deleted = 0

    for token in Token.objects.all().iterator():
        session = UserSession.objects.filter(
            user_id=token.user_id,
            token_hash=_token_hash(token.key),
        ).first()
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            Token.objects.filter(pk=token.pk).delete()
            deleted += 1

    print(f"Deleted {deleted} stale auth tokens.")


class Migration(migrations.Migration):
    dependencies = [
        ("authtoken", "0004_alter_tokenproxy_options"),
        ("users", "0001_security_profiles_and_sessions"),
    ]

    operations = [
        migrations.RunPython(delete_stale_tokens, migrations.RunPython.noop),
    ]
