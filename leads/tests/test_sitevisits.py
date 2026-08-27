from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership
from leads.models import Lead, Sitevisit, SitevisitReschedule


class SiteVisitApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="manager", password="test-pass")
        self.other_user = User.objects.create_user(username="other", password="test-pass")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.user, role=OrganizationMembership.Role.MANAGER
        )
        OrganizationMembership.objects.create(
            organization=self.other_organization, user=self.other_user, role=OrganizationMembership.Role.MANAGER
        )
        self.lead = Lead.objects.create(organization=self.organization, first_name="Ravi", phone="9999999999")
        self.other_lead = Lead.objects.create(organization=self.other_organization, first_name="Other", phone="8888888888")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.list_url = reverse("leads:site-visit", args=[self.organization.slug])

    def schedule(self, **overrides):
        payload = {
            "lead": self.lead.id,
            "executive": self.membership.id,
            "visit_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "visit_time": "10:00:00",
            "duration_minutes": 60,
            "site": "Green Valley",
        }
        payload.update(overrides)
        return self.client.post(self.list_url, payload, format="json")

    def test_schedule_and_90_day_validation(self):
        response = self.schedule()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["lead"]["id"], self.lead.id)
        self.assertEqual(response.data["status"], Sitevisit.Status.UPCOMING)
        self.assertEqual(self.schedule(executive=None).status_code, 400)
        response = self.schedule(visit_date=(timezone.localdate() + timedelta(days=91)).isoformat())
        self.assertEqual(response.status_code, 400)

    def test_other_organization_lead_is_not_schedulable_or_visible(self):
        response = self.schedule(lead=self.other_lead.id)
        self.assertEqual(response.status_code, 404)
        other_visit = Sitevisit.objects.create(
            organization=self.other_organization, lead=self.other_lead,
            visit_date=timezone.localdate(), visit_time="10:00", status=Sitevisit.Status.UPCOMING,
        )
        response = self.client.get(reverse("leads:site-visit-detail", args=[self.organization.slug, other_visit.id]))
        self.assertEqual(response.status_code, 404)

    def test_reschedule_creates_immutable_history_and_rejects_terminal_visit(self):
        visit = Sitevisit.objects.create(
            organization=self.organization, lead=self.lead, executive_membership=self.membership,
            visit_date=timezone.localdate() + timedelta(days=1), visit_time="10:00", status=Sitevisit.Status.UPCOMING,
        )
        url = reverse("leads:site-visit-reschedule", args=[self.organization.slug, visit.id])
        response = self.client.post(url, {"new_date": (timezone.localdate() + timedelta(days=2)).isoformat(), "new_time": "11:00", "reason": "Customer request"}, format="json")
        self.assertEqual(response.status_code, 201)
        visit.refresh_from_db()
        self.assertEqual(visit.reschedules.count(), 1)
        self.assertEqual(visit.status, Sitevisit.Status.RESCHEDULED)
        response = self.client.post(url, {"new_date": (timezone.localdate() + timedelta(days=3)).isoformat(), "new_time": "12:00"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(visit.reschedules.count(), 2)
        invalid_history = SitevisitReschedule(
            site_visit=visit, old_date=timezone.localdate(), old_time="09:00",
            new_date=timezone.localdate() + timedelta(days=4), new_time="13:00",
        )
        with self.assertRaises(ValidationError):
            invalid_history.full_clean()
        visit.status = Sitevisit.Status.COMPLETED
        visit.save(update_fields=["status"])
        response = self.client.post(url, {"new_date": (timezone.localdate() + timedelta(days=3)).isoformat(), "new_time": "12:00"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_cancel_and_outcome_transition_rules(self):
        visit = Sitevisit.objects.create(organization=self.organization, lead=self.lead, executive_membership=self.membership, visit_date=timezone.localdate(), visit_time="10:00", status=Sitevisit.Status.UPCOMING)
        cancel_url = reverse("leads:site-visit-cancel", args=[self.organization.slug, visit.id])
        self.assertEqual(self.client.post(cancel_url, {"cancellation_reason": "Customer unavailable"}, format="json").status_code, 200)
        self.assertEqual(self.client.post(cancel_url, {"cancellation_reason": "Again"}, format="json").status_code, 400)
        visit = Sitevisit.objects.create(organization=self.organization, lead=self.lead, executive_membership=self.membership, visit_date=timezone.localdate(), visit_time="10:00", status=Sitevisit.Status.IN_PROGRESS)
        outcome_url = reverse("leads:site-visit-outcome", args=[self.organization.slug, visit.id])
        self.assertEqual(self.client.post(outcome_url, {"outcome": "interested", "interest_level": 6}, format="json").status_code, 400)
        self.assertEqual(self.client.post(outcome_url, {"outcome": "interested", "interest_level": 5}, format="json").status_code, 200)
        visit.refresh_from_db()
        self.assertEqual(visit.status, Sitevisit.Status.COMPLETED)

    def test_no_show_requires_elapsed_visit_time(self):
        future = Sitevisit.objects.create(organization=self.organization, lead=self.lead, executive_membership=self.membership, visit_date=timezone.localdate() + timedelta(days=1), visit_time="10:00", status=Sitevisit.Status.UPCOMING)
        url = reverse("leads:site-visit-no-show", args=[self.organization.slug, future.id])
        self.assertEqual(self.client.post(url, {"after_minutes": 0}, format="json").status_code, 400)
        past = Sitevisit.objects.create(organization=self.organization, lead=self.lead, executive_membership=self.membership, visit_date=timezone.localdate() - timedelta(days=1), visit_time="10:00", status=Sitevisit.Status.UPCOMING)
        url = reverse("leads:site-visit-no-show", args=[self.organization.slug, past.id])
        self.assertEqual(self.client.post(url, {"after_minutes": 0}, format="json").status_code, 200)
        self.assertEqual(self.client.post(url, {"after_minutes": 0}, format="json").status_code, 400)

    def test_analytics_respects_date_range(self):
        Sitevisit.objects.create(organization=self.organization, lead=self.lead, executive_membership=self.membership, visit_date=timezone.localdate(), visit_time="10:00", status=Sitevisit.Status.COMPLETED, outcome="interested", interest_level=4)
        Sitevisit.objects.create(organization=self.organization, lead=self.lead, executive_membership=self.membership, visit_date=timezone.localdate() - timedelta(days=10), visit_time="10:00", status=Sitevisit.Status.CANCELLED)
        url = reverse("leads:site-visit-analytics", args=[self.organization.slug])
        response = self.client.get(url, {"start_date": timezone.localdate().isoformat(), "end_date": timezone.localdate().isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_visits"], 1)
        self.assertEqual(response.data["completed"], 1)
        self.assertEqual(response.data["average_interest_level"], 4.0)
