from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.tests.factories import make_lead, make_member, make_organization, make_project, project_request_kwargs
from leads.models import Sitevisit


class UatLc10SiteVisitTests(TestCase):
    """FR-P7-02/API-P7-03: a rescheduled visit can still be completed."""

    def setUp(self):
        self.organization = make_organization("uat-lc10")
        self.project = make_project(self.organization, "LC10")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.executive = make_member(self.organization, role="telecaller", projects=[self.project])
        self.lead = make_lead(self.organization, self.project, first_name="Rescheduled", lifecycle_status="site_visit_scheduled")
        self.client = APIClient()
        self.client.force_authenticate(self.manager.user)

    def headers(self):
        return project_request_kwargs(self.project)

    def test_time_only_edit_then_outcome_can_complete_lc10(self):
        create = self.client.post(
            reverse("leads:site-visit", args=[self.organization.slug]),
            {
                "lead": self.lead.pk,
                "executive": self.executive.pk,
                "visit_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "visit_time": "15:00:00",
                "duration_minutes": 60,
                "site": "UAT site",
            },
            format="json",
            **self.headers(),
        )
        self.assertEqual(create.status_code, 201, create.data)
        visit_id = create.data["id"]

        edit = self.client.patch(
            reverse("leads:site-visit-detail", args=[self.organization.slug, visit_id]),
            {"visit_time": "16:00:00"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(edit.status_code, 200, edit.data)
        self.assertEqual(edit.data["status"], Sitevisit.Status.RESCHEDULED)

        outcome = self.client.post(
            reverse("leads:site-visit-outcome", args=[self.organization.slug, visit_id]),
            {"outcome": "interested", "interest_level": 4},
            format="json",
            **self.headers(),
        )
        self.assertEqual(outcome.status_code, 200, outcome.data)
