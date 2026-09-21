from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from unittest.mock import patch
from rest_framework.test import APITestCase

from organizations.models import Organization, OrganizationMembership, Permission, Project
from organizations.services import ensure_default_roles
from system_settings.models import MasterData, SystemParameter
from system_settings.services import get_system_parameter


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "phase-2-system-parameters",
    }
}


class Phase2MasterDataCrudTests(APITestCase):
    """FR-P2-01 / DM-P2-01 / DM-P2-02 / API-P2-01..03."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="phase2-admin",
            email="phase2-admin@example.test",
            password="Password@123",
        )
        self.organization = Organization.objects.create(name="Phase 2 Org", slug="phase-2-org")
        ensure_default_roles(self.organization)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name="Green Acres",
            code="GREEN",
        )
        self.other_project = Project.objects.create(
            organization=self.organization,
            name="Blue Acres",
            code="BLUE",
        )
        self.client.force_authenticate(self.user)

    def use_project(self, project):
        self.client.credentials(HTTP_X_PROJECT_ID=project.code)

    def masters_url(self, category_code="lead_status"):
        return f"/api/v1/organizations/{self.organization.slug}/settings/masters/{category_code}/"

    def test_create_item_creates_and_links_canonical_category(self):
        self.use_project(self.project)

        response = self.client.post(
            self.masters_url(),
            {"code": "qualified", "name": "Qualified", "color": "#22AA44"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        category_model = apps.get_model("system_settings", "MasterDataCategory")
        category = category_model.all_objects.get(
            organization=self.organization,
            project=self.project,
            code="lead_status",
        )
        item = MasterData.all_objects.get(
            organization=self.organization,
            project=self.project,
            master_type="lead_status",
            code="qualified",
        )
        self.assertEqual(category.project_id, self.project.id)
        self.assertEqual(item.category_id, category.id)
        self.assertEqual(response.data["category"], {"id": category.id, "code": "lead_status", "name": "Lead Status"})

    def test_category_lookup_and_update_are_project_scoped(self):
        self.use_project(self.project)
        created = self.client.post(
            self.masters_url("lead_source"),
            {"code": "referral", "name": "Referral"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)

        updated = self.client.patch(
            f"{self.masters_url('lead_source')}{created.data['id']}/",
            {"name": "Customer Referral", "sort_order": 3},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["name"], "Customer Referral")

        self.use_project(self.other_project)
        other_project_list = self.client.get(self.masters_url("lead_source"))
        self.assertEqual(other_project_list.status_code, 200)
        self.assertEqual(other_project_list.data, [])

    def test_api_p2_03_put_replaces_master_data_item(self):
        self.use_project(self.project)
        created = self.client.post(
            self.masters_url("lead_status"),
            {"code": "warm", "name": "Warm", "description": "Old"},
            format="json",
        )

        response = self.client.put(
            f"{self.masters_url('lead_status')}{created.data['id']}/",
            {
                "code": "qualified",
                "name": "Qualified",
                "color": "#22AA44",
                "description": "Ready for follow-up",
                "is_active": True,
                "sort_order": 2,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["code"], "qualified")
        self.assertEqual(response.data["name"], "Qualified")
        self.assertEqual(response.data["sort_order"], 2)

    def test_duplicate_item_code_in_same_category_returns_validation_error(self):
        self.use_project(self.project)
        payload = {"code": "hot", "name": "Hot"}
        self.assertEqual(self.client.post(self.masters_url(), payload, format="json").status_code, 201)

        duplicate = self.client.post(self.masters_url(), payload, format="json")

        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("code", duplicate.data)
        self.assertEqual(MasterData.objects.filter(code="hot").count(), 1)

    def test_same_item_code_is_allowed_in_different_categories(self):
        self.use_project(self.project)

        first = self.client.post(
            self.masters_url("lead_status"),
            {"code": "active", "name": "Active Lead"},
            format="json",
        )
        second = self.client.post(
            self.masters_url("customer_status"),
            {"code": "active", "name": "Active Customer"},
            format="json",
        )

        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertEqual(MasterData.objects.filter(code="active").count(), 2)
        self.assertNotEqual(first.data["category"]["id"], second.data["category"]["id"])

    def test_expense_categories_use_generic_master_crud_and_active_consumer_lookup(self):
        self.use_project(self.project)
        created = self.client.post(
            self.masters_url("expense_category"),
            {"code": "travel", "name": "Travel", "description": "Travel expenses"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

        consumer_url = (
            f"/api/v1/organizations/{self.organization.slug}/master-data/expense_category/"
        )
        active = self.client.get(consumer_url)
        self.assertEqual(active.status_code, 200)
        self.assertEqual([item["code"] for item in active.data], ["travel"])

        deactivated = self.client.patch(
            f"{self.masters_url('expense_category')}{created.data['id']}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(deactivated.status_code, 200)
        self.assertEqual(self.client.get(consumer_url).data, [])

    def test_system_item_cannot_be_deleted_but_can_be_deactivated(self):
        self.use_project(self.project)
        item = MasterData.all_objects.create(
            organization=self.organization,
            project=self.project,
            master_type="plot_status",
            code="available",
            name="Available",
            is_system=True,
        )
        detail_url = f"{self.masters_url('plot_status')}{item.id}/"

        deletion = self.client.delete(detail_url, {"confirmation": True}, format="json")

        self.assertEqual(deletion.status_code, 409)
        self.assertEqual(deletion.data["code"], "protected_master_data")
        self.assertTrue(MasterData.all_objects.filter(pk=item.id).exists())

        deactivation = self.client.patch(
            detail_url,
            {"is_active": False, "is_system": False},
            format="json",
        )
        self.assertEqual(deactivation.status_code, 200)
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        self.assertTrue(item.is_system)
        self.assertTrue(deactivation.data["is_system"])

    def test_non_system_item_can_be_deleted_with_confirmation(self):
        self.use_project(self.project)
        created = self.client.post(
            self.masters_url("lead_source"),
            {"code": "campaign", "name": "Campaign"},
            format="json",
        )

        deletion = self.client.delete(
            f"{self.masters_url('lead_source')}{created.data['id']}/",
            {"confirmation": True},
            format="json",
        )

        self.assertEqual(deletion.status_code, 204)
        self.assertFalse(MasterData.all_objects.filter(pk=created.data["id"]).exists())

    def test_call_dispositions_are_provisioned_as_system_items(self):
        self.use_project(self.project)

        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/telecalling/dispositions/"
        )

        self.assertEqual(response.status_code, 200)
        dispositions = MasterData.all_objects.filter(
            organization=self.organization,
            project=self.project,
            master_type="call_disposition",
        )
        self.assertTrue(dispositions.exists())
        self.assertFalse(dispositions.filter(is_system=False).exists())


@override_settings(CACHES=TEST_CACHES)
class Phase2SystemParameterCacheTests(APITestCase):
    """FR-P2-02 / EC-P2-01 / DM-P2-03 / API-P2-04..05."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="phase2-parameter-admin",
            email="phase2-parameter-admin@example.test",
            password="Password@123",
        )
        self.organization = Organization.objects.create(name="Parameter Org", slug="parameter-org")
        ensure_default_roles(self.organization)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name="Parameter Project",
            code="PARAM",
        )
        self.other_project = Project.objects.create(
            organization=self.organization,
            name="Other Parameter Project",
            code="OTHER-PARAM",
        )
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_PROJECT_ID=self.project.code)
        self.url = f"/api/v1/organizations/{self.organization.slug}/settings/system-parameters/"

    def create_parameter(self, project, key="site_visit_reminder_days", value=2):
        return SystemParameter.all_objects.create(
            organization=self.organization,
            project=project,
            category="reminders",
            parameter_key=key,
            parameter_name=key.replace("_", " ").title(),
            value=value,
            data_type=SystemParameter.DataType.INTEGER,
        )

    def test_cache_aside_reuses_cached_value_without_second_database_read(self):
        self.create_parameter(self.project, value=2)
        self.assertEqual(
            get_system_parameter(self.organization, "site_visit_reminder_days", project=self.project),
            2,
        )

        with patch("system_settings.services.SystemParameter.objects.filter", side_effect=AssertionError("database read")):
            cached = get_system_parameter(
                self.organization,
                "site_visit_reminder_days",
                project=self.project,
            )

        self.assertEqual(cached, 2)

    def test_same_parameter_key_is_cached_separately_per_project(self):
        self.create_parameter(self.project, value=2)
        self.create_parameter(self.other_project, value=5)

        self.assertEqual(get_system_parameter(self.organization, "site_visit_reminder_days", project=self.project), 2)
        self.assertEqual(get_system_parameter(self.organization, "site_visit_reminder_days", project=self.other_project), 5)

    def test_api_update_invalidates_cache_for_site_visit_consumer(self):
        from leads.reminders import get_site_visit_reminder_days

        parameter = self.create_parameter(self.project, value=2)
        self.assertEqual(get_site_visit_reminder_days(self.organization, project=self.project), 2)

        response = self.client.patch(
            f"{self.url}{parameter.id}/",
            {"value": 4},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_site_visit_reminder_days(self.organization, project=self.project), 4)

    def test_api_p2_05_put_replaces_parameter_and_refreshes_consumer_cache(self):
        from leads.reminders import get_site_visit_reminder_days

        parameter = self.create_parameter(self.project, value=2)
        self.assertEqual(get_site_visit_reminder_days(self.organization, project=self.project), 2)

        response = self.client.put(
            f"{self.url}{parameter.id}/",
            {
                "category": "reminders",
                "parameter_key": "site_visit_reminder_days",
                "parameter_name": "Site visit reminder days",
                "value": "6",
                "data_type": "integer",
                "description": "Updated through API-P2-05",
                "is_active": True,
                "is_critical": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["value"], 6)
        self.assertEqual(get_site_visit_reminder_days(self.organization, project=self.project), 6)

    def test_api_create_and_delete_invalidate_cached_missing_or_existing_values(self):
        self.assertEqual(
            get_system_parameter(self.organization, "minimum_advance_payment_percent", default=10, project=self.project),
            10,
        )
        created = self.client.post(
            self.url,
            {
                "category": "booking",
                "parameter_key": "minimum_advance_payment_percent",
                "parameter_name": "Minimum advance payment percent",
                "value": 20,
                "data_type": "integer",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            get_system_parameter(self.organization, "minimum_advance_payment_percent", project=self.project),
            20,
        )

        deleted = self.client.delete(f"{self.url}{created.data['id']}/", {"confirmation": True}, format="json")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(
            get_system_parameter(self.organization, "minimum_advance_payment_percent", default=10, project=self.project),
            10,
        )


class Phase2AdminOnlyMutationTests(APITestCase):
    """FR-P2-04: only Admin/Super Admin may mutate Phase 2 configuration."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="phase2-role-admin",
            email="phase2-role-admin@example.test",
            password="Password@123",
        )
        self.manager = User.objects.create_user(
            username="phase2-role-manager",
            email="phase2-role-manager@example.test",
            password="Password@123",
        )
        self.superuser = User.objects.create_superuser(
            username="phase2-superuser",
            email="phase2-superuser@example.test",
            password="Password@123",
        )
        self.organization = Organization.objects.create(name="Role Org", slug="role-org")
        roles = ensure_default_roles(self.organization)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role=OrganizationMembership.Role.ADMIN,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.manager,
            role=OrganizationMembership.Role.MANAGER,
        )
        settings_view, _ = Permission.objects.get_or_create(
            module="settings", action="view", defaults={"name": "View settings"}
        )
        settings_edit, _ = Permission.objects.get_or_create(
            module="settings", action="edit", defaults={"name": "Edit settings"}
        )
        roles["manager"].permissions.add(settings_view, settings_edit)
        self.project = Project.objects.create(
            organization=self.organization,
            name="Role Project",
            code="ROLE",
        )
        self.master_url = f"/api/v1/organizations/{self.organization.slug}/settings/masters/lead_source/"
        self.parameter_url = f"/api/v1/organizations/{self.organization.slug}/settings/system-parameters/"
        self.client.credentials(HTTP_X_PROJECT_ID=self.project.code)

    def parameter_payload(self):
        return {
            "category": "reminders",
            "parameter_key": "site_visit_reminder_days",
            "parameter_name": "Site visit reminder days",
            "value": 2,
            "data_type": "integer",
        }

    def test_admin_and_superuser_can_create_phase2_configuration(self):
        self.client.force_authenticate(self.admin)
        admin_master = self.client.post(
            self.master_url,
            {"code": "website", "name": "Website"},
            format="json",
        )
        admin_parameter = self.client.post(self.parameter_url, self.parameter_payload(), format="json")

        self.assertEqual((admin_master.status_code, admin_parameter.status_code), (201, 201))

        self.client.force_authenticate(self.superuser)
        superuser_master = self.client.post(
            self.master_url,
            {"code": "referral", "name": "Referral"},
            format="json",
        )
        self.assertEqual(superuser_master.status_code, 201)

    def test_permission_granted_manager_can_read_but_cannot_create(self):
        self.client.force_authenticate(self.manager)

        self.assertEqual(self.client.get(self.master_url).status_code, 200)
        self.assertEqual(self.client.get(self.parameter_url).status_code, 200)
        self.assertEqual(
            self.client.post(self.master_url, {"code": "blocked", "name": "Blocked"}, format="json").status_code,
            403,
        )
        self.assertEqual(self.client.post(self.parameter_url, self.parameter_payload(), format="json").status_code, 403)

    def test_permission_granted_manager_cannot_update_or_delete(self):
        master = MasterData.all_objects.create(
            organization=self.organization,
            project=self.project,
            master_type="lead_source",
            code="existing",
            name="Existing",
        )
        parameter = SystemParameter.all_objects.create(
            organization=self.organization,
            project=self.project,
            category="reminders",
            parameter_key="site_visit_reminder_days",
            parameter_name="Site visit reminder days",
            value=2,
            data_type=SystemParameter.DataType.INTEGER,
        )
        self.client.force_authenticate(self.manager)

        master_detail = f"{self.master_url}{master.id}/"
        parameter_detail = f"{self.parameter_url}{parameter.id}/"
        responses = (
            self.client.patch(master_detail, {"name": "Changed"}, format="json"),
            self.client.delete(master_detail, {"confirmation": True}, format="json"),
            self.client.patch(parameter_detail, {"value": 4}, format="json"),
            self.client.delete(parameter_detail, {"confirmation": True}, format="json"),
        )

        self.assertEqual([response.status_code for response in responses], [403, 403, 403, 403])
        master.refresh_from_db()
        parameter.refresh_from_db()
        self.assertEqual(master.name, "Existing")
        self.assertEqual(parameter.value, 2)


class Phase2SystemParameterTypeTests(APITestCase):
    """NFR-P2-01: server-side type coercion and validation."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="phase2-type-admin",
            email="phase2-type-admin@example.test",
            password="Password@123",
        )
        self.organization = Organization.objects.create(name="Type Org", slug="type-org")
        ensure_default_roles(self.organization)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name="Type Project",
            code="TYPE",
        )
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_PROJECT_ID=self.project.code)
        self.url = f"/api/v1/organizations/{self.organization.slug}/settings/system-parameters/"

    def create_payload(self, key, data_type, value):
        return {
            "category": "typed",
            "parameter_key": key,
            "parameter_name": key.replace("_", " ").title(),
            "value": value,
            "data_type": data_type,
        }

    def test_api_coerces_string_integer_and_float_values(self):
        integer = self.client.post(
            self.url,
            self.create_payload("integer_value", "integer", "42"),
            format="json",
        )
        floating = self.client.post(
            self.url,
            self.create_payload("float_value", "float", "12.5"),
            format="json",
        )
        string = self.client.post(
            self.url,
            self.create_payload("string_value", "string", 123),
            format="json",
        )

        self.assertEqual([integer.status_code, floating.status_code, string.status_code], [201, 201, 201])
        self.assertEqual(integer.data["value"], 42)
        self.assertIsInstance(integer.data["value"], int)
        self.assertEqual(floating.data["value"], 12.5)
        self.assertIsInstance(floating.data["value"], float)
        self.assertEqual(string.data["value"], "123")

    def test_invalid_numeric_conversions_are_rejected_without_rows(self):
        invalid_values = (
            ("bad_integer", "integer", "4.2"),
            ("boolean_integer", "integer", True),
            ("bad_float", "float", "not-a-number"),
            ("non_finite_float", "float", "NaN"),
        )

        for key, data_type, value in invalid_values:
            with self.subTest(key=key):
                response = self.client.post(
                    self.url,
                    self.create_payload(key, data_type, value),
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("value", response.data)

        self.assertEqual(SystemParameter.all_objects.filter(organization=self.organization).count(), 0)

    def test_data_type_change_converts_existing_value_and_failed_change_is_atomic(self):
        created = self.client.post(
            self.url,
            self.create_payload("changeable", "integer", "5"),
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        detail = f"{self.url}{created.data['id']}/"

        converted = self.client.patch(detail, {"data_type": "string"}, format="json")
        self.assertEqual(converted.status_code, 200)
        self.assertEqual(converted.data["value"], "5")

        rejected = self.client.patch(
            detail,
            {"data_type": "float", "value": "invalid"},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        parameter = SystemParameter.all_objects.get(pk=created.data["id"])
        self.assertEqual(parameter.data_type, SystemParameter.DataType.STRING)
        self.assertEqual(parameter.value, "5")


class Phase2ActiveMasterDataLookupTests(APITestCase):
    """NFR-P2-02: consumer lookups expose active items only."""

    def setUp(self):
        User = get_user_model()
        self.telecaller = User.objects.create_user(
            username="phase2-lookup-user",
            email="phase2-lookup@example.test",
            password="Password@123",
        )
        self.outsider = User.objects.create_user(
            username="phase2-lookup-outsider",
            email="phase2-lookup-outsider@example.test",
            password="Password@123",
        )
        self.organization = Organization.objects.create(name="Lookup Org", slug="lookup-org")
        ensure_default_roles(self.organization)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.telecaller,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name="Lookup Project",
            code="LOOKUP",
        )
        self.other_project = Project.objects.create(
            organization=self.organization,
            name="Other Lookup Project",
            code="OTHER-LOOKUP",
        )
        MasterData.all_objects.create(
            organization=self.organization,
            project=self.project,
            master_type="lead_source",
            code="website",
            name="Website",
            is_active=True,
            sort_order=2,
        )
        MasterData.all_objects.create(
            organization=self.organization,
            project=self.project,
            master_type="lead_source",
            code="old_campaign",
            name="Old Campaign",
            is_active=False,
            sort_order=1,
        )
        MasterData.all_objects.create(
            organization=self.organization,
            project=self.other_project,
            master_type="lead_source",
            code="other_project_source",
            name="Other Project Source",
            is_active=True,
        )
        self.url = f"/api/v1/organizations/{self.organization.slug}/master-data/lead_source/"
        self.client.credentials(HTTP_X_PROJECT_ID=self.project.code)

    def test_non_admin_lookup_returns_only_active_current_project_items(self):
        self.client.force_authenticate(self.telecaller)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["code"] for item in response.data], ["website"])
        self.assertTrue(all(item["is_active"] for item in response.data))

    def test_unknown_category_returns_empty_lookup(self):
        self.client.force_authenticate(self.telecaller)

        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/master-data/unknown_category/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_lead_status_lookup_provisions_exact_protected_lifecycle_catalogue(self):
        self.client.force_authenticate(self.telecaller)

        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/master-data/lead_status/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["code"] for item in response.data],
            [
                "new",
                "contacted",
                "interested",
                "site_visit_scheduled",
                "site_visit_completed",
                "converted",
                "lost",
            ],
        )
        self.assertTrue(all(item["is_system"] for item in response.data))

    def test_lookup_rejects_unauthenticated_and_cross_organization_users(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
