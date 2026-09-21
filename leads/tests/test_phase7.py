from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import Lead, Sitevisit
from organizations.models import Organization, OrganizationMembership
from system_settings.models import SystemParameter


class Phase7SiteVisitTests(TestCase):
    """Phase 7: scheduling, lifecycle, outcome and lead integration."""

    def setUp(self):
        user_model = get_user_model()
        self.manager_user = user_model.objects.create_user(username="phase7-manager", password="test-pass")
        self.executive_user = user_model.objects.create_user(username="phase7-executive", password="test-pass")
        self.organization = Organization.objects.create(name="Phase 7 CRM", slug="phase7-crm")
        self.manager = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.manager_user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.executive = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.executive_user,
            role="site_visit_exec",
        )
        self.lead = Lead.objects.create(
            organization=self.organization,
            first_name="Phase",
            phone="9555555555",
            status="site_visit_scheduled",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.manager_user)
        self.list_url = reverse("leads:site-visit", args=[self.organization.slug])

    def schedule(self, **overrides):
        payload = {
            "lead": self.lead.id,
            "executive": self.executive.id,
            "visit_date": (timezone.localdate() + timedelta(days=2)).isoformat(),
            "visit_time": "10:00:00",
            "duration_minutes": 60,
            "site": "Phase 7 Site",
        }
        payload.update(overrides)
        return self.client.post(self.list_url, payload, format="json")

    def test_fr_p7_01_rejects_overlapping_executive_schedule(self):
        first = self.schedule()
        self.assertEqual(first.status_code, 201, first.data)

        conflict = self.schedule()
        self.assertEqual(conflict.status_code, 400, conflict.data)
        self.assertIn("executive", conflict.data)

    def test_fr_p7_05_rejects_inactive_lead(self):
        self.lead.status = "lost"
        self.lead.save(update_fields=["status"])

        response = self.schedule()

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("lead", response.data)

    def test_fr_p7_06_uses_configurable_future_day_limit(self):
        SystemParameter.all_objects.create(
            organization=self.organization,
            category="site_visits",
            parameter_key="site_visit_max_days_ahead",
            parameter_name="Site visit max days ahead",
            value=30,
            data_type=SystemParameter.DataType.INTEGER,
        )
        cache.clear()

        response = self.schedule(visit_date=(timezone.localdate() + timedelta(days=31)).isoformat())

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("visit_date", response.data)

    def test_fr_p7_02_03_04_completion_updates_score_and_lead_status(self):
        visit = Sitevisit.objects.create(
            organization=self.organization,
            lead=self.lead,
            executive_membership=self.executive,
            visit_date=timezone.localdate(),
            visit_time="10:00",
            duration_minutes=60,
            status=Sitevisit.Status.IN_PROGRESS,
        )
        outcome_url = reverse("leads:site-visit-outcome", args=[self.organization.slug, visit.id])

        response = self.client.post(
            outcome_url,
            {"outcome": "interested", "interest_level": 4, "remarks": "Positive visit."},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        visit.refresh_from_db()
        self.lead.refresh_from_db()
        self.assertEqual(visit.status, Sitevisit.Status.COMPLETED)
        self.assertEqual(visit.interest_level, 4)
        self.assertEqual(self.lead.score, 20)
        self.assertEqual(self.lead.status, "site_visit_completed")

    def test_fr_p7_02_rejects_completion_without_in_progress_state(self):
        visit = Sitevisit.objects.create(
            organization=self.organization,
            lead=self.lead,
            executive_membership=self.executive,
            visit_date=timezone.localdate(),
            visit_time="10:00",
            duration_minutes=60,
            status=Sitevisit.Status.UPCOMING,
        )
        outcome_url = reverse("leads:site-visit-outcome", args=[self.organization.slug, visit.id])

        response = self.client.post(
            outcome_url,
            {"outcome": "interested", "interest_level": 4},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        visit.refresh_from_db()
        self.lead.refresh_from_db()
        self.assertEqual(visit.status, Sitevisit.Status.UPCOMING)
        self.assertEqual(self.lead.score, 0)

    def test_fr_p7_07_executive_scope_is_limited_to_owned_visits(self):
        visit = Sitevisit.objects.create(
            organization=self.organization,
            lead=self.lead,
            executive_membership=self.executive,
            visit_date=timezone.localdate() + timedelta(days=1),
            visit_time="11:00",
            duration_minutes=30,
            status=Sitevisit.Status.UPCOMING,
        )
        self.client.force_authenticate(self.executive_user)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], visit.id)
