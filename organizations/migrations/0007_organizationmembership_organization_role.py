import django.db.models.deletion
from django.db import migrations, models


CATALOGUE = {
    "dashboard": ("view",), "leads": ("view", "add", "edit", "delete", "export"),
    "customers": ("view", "add", "edit", "delete", "export"), "plots": ("view", "add", "edit", "delete", "export"),
    "payments": ("view", "add", "edit", "delete", "export"), "registry": ("view", "add", "edit", "delete", "export"),
    "reports": ("view", "export"), "employees": ("view", "add", "edit", "delete", "export"),
    "expenses": ("view", "add", "edit", "delete", "export"), "communication": ("view", "add", "edit", "delete", "export"),
    "settings": ("view", "edit"), "documents": ("view", "add", "edit", "delete"), "attendance": ("view", "add", "edit", "manage"), "leave": ("view", "add", "edit", "approve", "manage"),
    "employee": ("view", "create", "update", "delete", "manage"), "role": ("view", "create", "update", "delete", "manage"),
}


def migrate_roles(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission"); Role = apps.get_model("organizations", "OrganizationRole")
    Org = apps.get_model("organizations", "Organization"); Membership = apps.get_model("organizations", "OrganizationMembership")
    permissions = []
    for module, actions in CATALOGUE.items():
        for action in actions:
            item, _ = Permission.objects.get_or_create(module=module, action=action, defaults={"name": f"{action.title()} {module.title()}"})
            permissions.append(item)
    codes = {f"{p.module}.{p.action}": p for p in permissions}
    admin_permissions = list(Permission.objects.all())
    manager_codes = {"dashboard.view", "leads.view", "leads.add", "leads.edit", "customers.view", "customers.add", "customers.edit", "plots.view", "plots.add", "plots.edit", "documents.view", "documents.add", "employees.view", "employees.add", "employees.edit", "attendance.view", "attendance.add", "attendance.manage", "leave.view", "leave.add", "leave.approve"}
    telecaller_codes = {"dashboard.view", "leads.view", "leads.add", "leads.edit", "customers.view", "customers.add", "documents.view", "documents.add"}
    for org in Org.objects.all():
        role_map = {}
        for code, name in (("admin", "Organization admin"), ("manager", "Manager"), ("telecaller", "Telecaller")):
            role, _ = Role.objects.get_or_create(organization=org, code=code, defaults={"name": name, "is_system": True})
            role_map[code] = role
        role_map["admin"].permissions.set(admin_permissions)
        role_map["manager"].permissions.set([codes[x] for x in manager_codes if x in codes])
        role_map["telecaller"].permissions.set([codes[x] for x in telecaller_codes if x in codes])
        for membership in Membership.objects.filter(organization=org):
            membership.organization_role = role_map.get(membership.role, role_map["telecaller"])
            membership.save(update_fields=["organization_role"])


class Migration(migrations.Migration):
    dependencies = [("organizations", "0006_employee_phase2")]
    operations = [
        migrations.AddField(model_name="organizationmembership", name="organization_role", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="memberships", to="organizations.organizationrole")),
        migrations.RunPython(migrate_roles, migrations.RunPython.noop),
    ]
