from django.apps import AppConfig


class SystemSettingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "system_settings"

    def ready(self):
        from django.db.models.signals import post_save
        from organizations.models import Organization
        from inventory.models import Project
        from .services import clone_project_defaults, ensure_lead_master_data_defaults, ensure_organization_parameter_defaults

        def organization_defaults(sender, instance, created, **kwargs):
            if created:
                ensure_organization_parameter_defaults(instance)
                ensure_lead_master_data_defaults(instance)

        def project_defaults(sender, instance, created, **kwargs):
            if created:
                clone_project_defaults(instance)

        post_save.connect(organization_defaults, sender=Organization, dispatch_uid="system-settings-organization-defaults")
        post_save.connect(project_defaults, sender=Project, dispatch_uid="system-settings-project-defaults")
