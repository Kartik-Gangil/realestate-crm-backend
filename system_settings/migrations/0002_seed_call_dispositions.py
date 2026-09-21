from django.db import migrations


DISPOSITIONS = (
    ("interested", "Interested"),
    ("callback_later", "Callback Later"),
    ("busy", "Busy"),
    ("no_answer", "No Answer"),
    ("switched_off", "Switched Off"),
    ("wrong_number", "Wrong Number"),
    ("dnd", "DND"),
    ("already_purchased", "Already Purchased"),
)


def seed_call_dispositions(apps, schema_editor):
    organization_model = apps.get_model("organizations", "Organization")
    master_data_model = apps.get_model("system_settings", "MasterData")
    for organization in organization_model.objects.all().iterator():
        for sort_order, (code, name) in enumerate(DISPOSITIONS, start=1):
            master_data_model.objects.get_or_create(
                organization=organization,
                master_type="call_disposition",
                code=code,
                defaults={"name": name, "sort_order": sort_order},
            )


def unseed_call_dispositions(apps, schema_editor):
    master_data_model = apps.get_model("system_settings", "MasterData")
    master_data_model.objects.filter(
        master_type="call_disposition",
        code__in=[code for code, _name in DISPOSITIONS],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("system_settings", "0001_initial")]
    operations = [migrations.RunPython(seed_call_dispositions, unseed_call_dispositions)]
