from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project
from organizations.models import OrganizationMembership
from system_settings.models import MasterData, MasterDataCategory, SystemParameter
from system_settings.parameters import PARAMETER_REGISTRY
from system_settings.services import UnknownSystemParameter, get_system_parameter


class Phase2MasterDataAndParametersTests(TestCase):
    """FR/DM/API/NFR-P2 and G-1 item 4 coverage for Task 10 / Phase 2."""

    def setUp(self):
        cache.clear()
        self.organization = make_organization("phase2-contracts")
        self.project = make_project(self.organization, "P2")
        membership = make_member(
            self.organization,
            role=OrganizationMembership.Role.ADMIN,
            projects=[self.project],
        )
        self.user = membership.user
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_categories_and_properties_replace_master_type_dm_p2_01_dm_p2_02(self):
        category = MasterDataCategory.objects.get(code="plot_status")
        item = MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=category,
            code="available",
            name="Available",
            color="#00AA00",
            properties={"terminal": False},
        )

        self.assertEqual(item.category.code, "plot_status")
        self.assertEqual(item.properties, {"terminal": False})
        self.assertFalse(hasattr(item, "master_type"))

    def test_system_item_key_and_system_flag_are_immutable_but_other_fields_change_fr_p2_03(self):
        category = MasterDataCategory.objects.get(code="plot_status")
        item = MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=category,
            code="available",
            name="Available",
            is_system=True,
        )

        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/master-data/{category.code}/{item.pk}/",
            {
                "category": category.code,
                "key": "changed",
                "value": "Open",
                "color_code": "#112233",
                "properties": {"terminal": False},
                "is_active": False,
                "sort_order": 4,
            },
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

        self.assertEqual(response.status_code, 400, response.data)
        item.refresh_from_db()
        self.assertEqual(item.code, "available")
        self.assertTrue(item.is_system)

        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/master-data/{category.code}/{item.pk}/",
            {
                "category": category.code,
                "key": "available",
                "value": "Open",
                "color_code": "#112233",
                "properties": {"terminal": False},
                "is_active": False,
                "sort_order": 4,
            },
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

        self.assertEqual(response.status_code, 200, response.data)
        item.refresh_from_db()
        self.assertEqual(item.name, "Open")
        self.assertFalse(item.is_active)

    def test_master_data_api_scopes_and_hides_inactive_items_for_non_admins_api_p2_01_api_p2_03_nfr_p2_02(self):
        category = MasterDataCategory.objects.create(
            code="test_master_data_scope",
            name="Test master data scope",
            is_system=False,
        )
        MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=category,
            code="active",
            name="Active",
            sort_order=2,
        )
        MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=category,
            code="inactive",
            name="Inactive",
            is_active=False,
            sort_order=1,
        )

        manager = make_member(self.organization, role="manager", projects=[self.project]).user
        self.client.force_authenticate(manager)
        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/master-data/{category.code}/",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["key"] for row in response.json()["data"]], ["active"])

    def test_non_admin_cannot_edit_master_data_or_parameters_fr_p2_04_nfr_p2_02(self):
        category = MasterDataCategory.objects.get(code="lead_source")
        item = MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=category,
            code="existing",
            name="Existing",
        )
        manager = make_member(self.organization, role="manager", projects=[self.project]).user
        self.client.force_authenticate(manager)

        master_response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/master-data/",
            {"category": category.code, "key": "new", "value": "New"},
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )
        update_response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/master-data/{category.code}/{item.pk}/",
            {"value": "Changed"},
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )
        parameter_response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/system-parameters/",
            {"parameter_key": "site_visit_max_days_ahead", "value": 120},
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

        self.assertEqual(master_response.status_code, 403, master_response.data)
        self.assertEqual(update_response.status_code, 403, update_response.data)
        self.assertEqual(parameter_response.status_code, 403, parameter_response.data)

    def test_project_master_data_post_api_p2_02(self):
        category = MasterDataCategory.objects.get(code="document_type")
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/master-data/",
            {
                "category": category.code,
                "key": "sale_deed",
                "value": "Sale deed",
                "color_code": "#112233",
                "properties": {"requires_signature": True},
                "sort_order": 1,
            },
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.json()["data"]["key"], "sale_deed")

    def test_project_master_data_put_api_p2_03(self):
        category = MasterDataCategory.objects.get(code="document_type")
        item = MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=category,
            code="sale_deed",
            name="Sale deed",
        )

        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/master-data/{category.code}/{item.pk}/",
            {"value": "Registered sale deed", "color_code": "#112233", "sort_order": 2},
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()["data"]["value"], "Registered sale deed")

    def test_parameter_registry_types_ranges_unknown_keys_and_cache_invalidation_dm_p2_03_ec_p2_01_nfr_p2_01(self):
        definition = PARAMETER_REGISTRY["site_visit_max_days_ahead"]
        parameter = SystemParameter.objects.get(
            organization=self.organization,
            project=self.project,
            parameter_key="site_visit_max_days_ahead",
        )

        self.assertEqual(get_system_parameter(self.organization, parameter.parameter_key, project=self.project), 90)
        parameter.value = 120
        parameter.save(update_fields=["value"])
        self.assertEqual(get_system_parameter(self.organization, parameter.parameter_key, project=self.project), 90)

        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/system-parameters/",
            {"parameter_key": "site_visit_max_days_ahead", "value": 120},
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(get_system_parameter(self.organization, parameter.parameter_key, project=self.project), 120)

        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/system-parameters/",
            {"parameter_key": "site_visit_max_days_ahead", "value": "not-an-integer"},
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )
        self.assertEqual(response.status_code, 400, response.data)

        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/system-parameters/",
            {"parameter_key": "not_registered", "value": 10},
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_organization_parameter_cache_ignores_project_for_defaults_ec_p2_01(self):
        self.assertEqual(
            get_system_parameter(self.organization, "auto_logout_minutes", project=self.project),
            30,
        )

        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/system-parameters/defaults/",
            {"parameter_key": "auto_logout_minutes", "value": 45},
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            get_system_parameter(self.organization, "auto_logout_minutes", project=self.project),
            45,
        )

    def test_missing_project_parameter_does_not_fall_back_to_organization_default_g1_item_4(self):
        definition = PARAMETER_REGISTRY["site_visit_max_days_ahead"]
        SystemParameter.objects.create(
            organization=self.organization,
            project=None,
            parameter_key=definition.key,
            parameter_name=definition.name,
            value=definition.default,
            data_type=definition.data_type,
        )
        parameter = SystemParameter.objects.get(
            organization=self.organization,
            project=self.project,
            parameter_key="site_visit_max_days_ahead",
        )
        parameter.delete()

        with self.assertRaises(UnknownSystemParameter):
            get_system_parameter(
                self.organization,
                "site_visit_max_days_ahead",
                project=self.project,
            )

    def test_organization_defaults_are_copied_to_new_project_and_never_retroactively_changed_g1_item_4(self):
        category = MasterDataCategory.objects.get(code="payment_mode")
        MasterData.objects.create(
            organization=self.organization,
            category=category,
            code="cash",
            name="Cash",
            is_system=True,
        )
        SystemParameter.objects.create(
            organization=self.organization,
            parameter_key="booking_hold_days",
            parameter_name=PARAMETER_REGISTRY["booking_hold_days"].name,
            value=7,
            data_type=SystemParameter.DataType.INTEGER,
        )

        project = make_project(self.organization, "P2-COPY")
        self.assertTrue(MasterData.objects.filter(project=project, category=category, code="cash").exists())
        self.assertTrue(SystemParameter.objects.filter(project=project, parameter_key="booking_hold_days").exists())

        MasterData.objects.filter(organization=self.organization, project__isnull=True, code="cash").update(name="Changed default")
        self.assertEqual(MasterData.objects.get(project=project, code="cash").name, "Cash")

    def test_organization_scope_rejects_project_parameter_for_org_only_key_api_p2_05(self):
        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/system-parameters/",
            {"parameter_key": "auto_logout_minutes", "value": 45},
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_general_settings_returns_backend_choices_and_validates_them_gnfr_09(self):
        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/settings/general/",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("choices", response.json()["data"])
        self.assertIn("YYYY-MM-DD", response.json()["data"]["choices"]["date_formats"])

        response = self.client.patch(
            f"/api/v1/organizations/{self.organization.slug}/settings/general/",
            {"date_format": "not-a-format"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_organization_default_master_data_collection_supports_get_and_post_api_p2_01_api_p2_02(self):
        category = MasterDataCategory.objects.get(code="document_type")
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/master-data/defaults/",
            {"category": category.code, "key": "sale_deed", "value": "Sale deed", "color_code": "#112233", "properties": {}, "sort_order": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/master-data/defaults/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("sale_deed", [row["key"] for row in response.json()["data"]])

