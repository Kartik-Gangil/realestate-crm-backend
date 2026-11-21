from django.db import migrations, models
from django.db.models import Count, Q


def stop_on_customer_collisions(apps, schema_editor):
    Customer = apps.get_model("inventory", "Customer")
    counts = {}
    for field in ("phone", "email", "government_id_hash"):
        counts[field] = (
            Customer.objects.filter(**{"project_id__isnull": False})
            .exclude(**{field: ""})
            .values("project_id", field)
            .annotate(row_count=Count("id"))
            .filter(row_count__gt=1)
            .count()
        )
    if any(counts.values()):
        raise RuntimeError(
            "Customer uniqueness migration stopped; collisions by project: "
            f"phone={counts['phone']}, email={counts['email']}, government_id_hash={counts['government_id_hash']}"
        )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0019_phase10_customer_360")]

    operations = [
        migrations.RunPython(stop_on_customer_collisions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                condition=~Q(phone=""), fields=("project", "phone"), name="inventory_customer_project_phone_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                condition=~Q(email=""), fields=("project", "email"), name="inventory_customer_project_email_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                condition=~Q(government_id_hash=""), fields=("project", "government_id_hash"), name="inventory_customer_project_id_hash_unique"
            ),
        ),
    ]
