from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("users", "0002_cleanup_stale_tokens"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeveloperAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="developer_account", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
