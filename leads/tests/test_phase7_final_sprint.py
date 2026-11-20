from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.models import Lead, Sitevisit


class Phase7FinalSprintTests(TestCase):
    def setUp(self):
        self.organization = make_organization("phase7")
        self.project = make_project(self.organization, "P7")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.executive = make_member(self.organization, role="telecaller", projects=[self.project])
        self.other_executive = make_member(self.organization, role="telecaller", projects=[self.project])
        self.lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            assigned_membership=self.executive,
            first_name="Phase Seven",
            phone="9999999901",
            score=40,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.manager.user)

    def headers(self):
        return project_request_kwargs(self.project)

    def schedule(self, **overrides):
        payload = {
            "lead": self.lead.id,
            "executive": self.executive.id,
            "visit_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "visit_time": "10:00:00",
            "duration_minutes": 60,
            "site": "Phase Seven Site",
        }
        payload.update(overrides)
        return self.client.post(
            reverse("leads:site-visit", args=[self.organization.slug]),
            payload,
            format="json",
            **self.headers(),
        )

    def test_scheduling_rejects_executive_conflict(self):
        self.assertEqual(self.schedule().status_code, 201)
        response = self.schedule(lead=Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Second Lead",
            phone="9999999902",
        ).id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("executive", response.data)

    def test_completion_boosts_linked_lead_score_by_twenty(self):
        visit = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            executive_membership=self.executive,
            visit_date=timezone.localdate(),
            visit_time="10:00",
            status=Sitevisit.Status.IN_PROGRESS,
        )
        response = self.client.post(
            reverse("leads:site-visit-outcome", args=[self.organization.slug, visit.id]),
            {"outcome": "interested", "interest_level": 5},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.score, 60)
        self.assertEqual(self.lead.lifecycle_status, "site_visit_completed")

    def test_scheduling_moves_lead_to_site_visit_scheduled(self):
        response = self.schedule()
        self.assertEqual(response.status_code, 201)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.lifecycle_status, "site_visit_scheduled")

    def test_converted_leads_are_not_schedulable(self):
        self.lead.lifecycle_status = "converted"
        self.lead.save(update_fields=["lifecycle_status", "updated_at"])
        response = self.schedule()
        self.assertEqual(response.status_code, 400)
        self.assertIn("lead", response.data)

    def test_non_manager_cannot_reassign_an_existing_visit(self):
        visit = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            executive_membership=self.executive,
            visit_date=timezone.localdate() + timedelta(days=1),
            visit_time="10:00",
            status=Sitevisit.Status.UPCOMING,
        )
        self.client.force_authenticate(self.executive.user)
        response = self.client.patch(
            reverse("leads:site-visit-detail", args=[self.organization.slug, visit.id]),
            {"executive": self.other_executive.id},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 403)
