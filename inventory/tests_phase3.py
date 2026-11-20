from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from organizations.models import OrganizationMembership, OrganizationRole, Permission, ProjectAssignment

from .models import Block, Plot, PlotHold, PlotStatusHistory


class PlotStatusLifecycleTests(TestCase):
    def setUp(self):
        self.organization = make_organization("acme")
        self.other_organization = make_organization("other")
        self.project = make_project(self.organization, "GA")
        self.block = Block.objects.create(organization=self.organization, project=self.project, name="A Block", code="A")
        self.other_project = make_project(self.other_organization, "F")
        self.other_block = Block.objects.create(organization=self.other_organization, project=self.other_project, name="Foreign Block", code="F")
        self.user_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.telecaller_membership = make_member(self.organization, role="telecaller", projects=[self.project])
        self.other_membership = make_member(self.other_organization, role="manager", projects=[self.other_project])
        self.user = self.user_membership.user
        self.telecaller = self.telecaller_membership.user
        self.other_user = self.other_membership.user
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def headers(self):
        return project_request_kwargs(self.project)

    def plot(self, status=Plot.Status.AVAILABLE, number="A-101"):
        return Plot.objects.create(
            organization=self.organization, project=self.project, block=self.block,
            plot_number=number, size=Decimal("120.00"), status=status,
        )

    def other_plot(self):
        return Plot.objects.create(
            organization=self.other_organization, project=self.other_project, block=self.other_block,
            plot_number="F-101", size=Decimal("120.00"),
        )

    def operation_url(self, plot, operation):
        return reverse(f"inventory:plot-{operation}", args=[self.organization.slug, plot.id])

    def status_url(self, plot):
        return self.operation_url(plot, "status")

    def status_payload(self, new_status, reason="Lifecycle reason"):
        return {"status": new_status, "reason": reason}

    def test_all_supported_transitions(self):
        transitions = {
            Plot.Status.AVAILABLE: [Plot.Status.BLOCKED, Plot.Status.HOLD, Plot.Status.BOOKED, Plot.Status.UNDER_CONSTRUCTION],
            Plot.Status.BLOCKED: [Plot.Status.AVAILABLE, Plot.Status.HOLD],
            Plot.Status.HOLD: [Plot.Status.AVAILABLE, Plot.Status.BOOKED],
            Plot.Status.BOOKED: [Plot.Status.SOLD, Plot.Status.CANCELLED],
            Plot.Status.SOLD: [Plot.Status.CANCELLED],
            Plot.Status.CANCELLED: [Plot.Status.AVAILABLE],
            Plot.Status.UNDER_CONSTRUCTION: [Plot.Status.AVAILABLE, Plot.Status.BLOCKED, Plot.Status.HOLD, Plot.Status.BOOKED],
        }
        sequence = 0
        for old_status, targets in transitions.items():
            for new_status in targets:
                sequence += 1
                plot = self.plot(old_status, f"A-{sequence}")
                response = self.client.post(self.status_url(plot), self.status_payload(new_status), format="json", **self.headers())
                self.assertEqual(response.status_code, 200, response.data)
                plot.refresh_from_db()
                self.assertEqual(plot.status, new_status)
                self.assertTrue(PlotStatusHistory.objects.filter(plot=plot, old_status=old_status, new_status=new_status).exists())

    def test_invalid_and_same_status_transitions_are_rejected_without_history(self):
        for old_status, new_status in [
            (Plot.Status.AVAILABLE, Plot.Status.SOLD),
            (Plot.Status.AVAILABLE, Plot.Status.CANCELLED),
            (Plot.Status.SOLD, Plot.Status.BOOKED),
            (Plot.Status.SOLD, Plot.Status.AVAILABLE),
            (Plot.Status.BOOKED, Plot.Status.AVAILABLE),
            (Plot.Status.AVAILABLE, Plot.Status.AVAILABLE),
        ]:
            plot = self.plot(old_status, f"A-{old_status}-{new_status}")
            response = self.client.post(self.status_url(plot), self.status_payload(new_status), format="json", **self.headers())
            self.assertEqual(response.status_code, 400)
            self.assertEqual(PlotStatusHistory.objects.filter(plot=plot).count(), 0)

    def test_reason_is_required_for_block_hold_and_cancel(self):
        available = self.plot(number="A-reason-1")
        self.assertEqual(self.client.post(self.status_url(available), {"status": "blocked"}, format="json", **self.headers()).status_code, 400)
        self.assertEqual(self.client.post(self.status_url(available), {"status": "hold"}, format="json", **self.headers()).status_code, 400)
        booked = self.plot(Plot.Status.BOOKED, "A-reason-2")
        self.assertEqual(self.client.post(self.status_url(booked), {"status": "cancelled"}, format="json", **self.headers()).status_code, 400)

    def test_history_is_immutable_and_history_api_is_newest_first(self):
        plot = self.plot()
        self.client.post(self.status_url(plot), self.status_payload("blocked", "Initial block"), format="json", **self.headers())
        self.client.post(self.status_url(plot), self.status_payload("available", "Released"), format="json", **self.headers())
        history = list(PlotStatusHistory.objects.filter(plot=plot).order_by("changed_at", "id"))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].reason, "Initial block")
        history[0].reason = "Changed"
        with self.assertRaises(ValidationError):
            history[0].save()
        response = self.client.get(reverse("inventory:plot-history", args=[self.organization.slug, plot.id]), **self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["new_status"], Plot.Status.AVAILABLE)

    def test_block_hold_and_release_create_and_preserve_hold_records(self):
        plot = self.plot()
        response = self.client.post(self.operation_url(plot, "block"), {"reason": "Customer request"}, format="json", **self.headers())
        self.assertEqual(response.status_code, 200)
        record = PlotHold.objects.get(plot=plot)
        self.assertEqual(record.action_type, PlotHold.ActionType.BLOCK)
        response = self.client.post(self.operation_url(plot, "release"), {"reason": "Request withdrawn"}, format="json", **self.headers())
        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        self.assertIsNotNone(record.released_at)
        self.assertEqual(PlotHold.objects.filter(plot=plot).count(), 1)

        response = self.client.post(self.operation_url(plot, "hold"), {"reason": "Customer hold"}, format="json", **self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PlotHold.objects.filter(plot=plot, action_type=PlotHold.ActionType.HOLD).count(), 1)

    def test_invalid_block_hold_and_release_are_rejected(self):
        booked = self.plot(Plot.Status.BOOKED, "A-booked")
        self.assertEqual(self.client.post(self.operation_url(booked, "block"), {"reason": "x"}, format="json", **self.headers()).status_code, 409)
        self.assertEqual(self.client.post(self.operation_url(booked, "hold"), {"reason": "x"}, format="json", **self.headers()).status_code, 409)
        self.assertEqual(self.client.post(self.operation_url(booked, "release"), {"reason": "x"}, format="json", **self.headers()).status_code, 400)

    def test_hold_range_and_overlap_rules(self):
        plot = self.plot()
        now = timezone.now()
        PlotHold.objects.create(
            plot=plot, action_type=PlotHold.ActionType.HOLD, reason="Existing",
            from_datetime=now, to_datetime=now + timedelta(hours=2), created_by=self.user,
        )
        payload = {
            "reason": "New", "from_datetime": (now + timedelta(hours=1)).isoformat(),
            "to_datetime": (now + timedelta(hours=3)).isoformat(),
        }
        self.assertEqual(self.client.post(self.operation_url(plot, "hold"), payload, format="json", **self.headers()).status_code, 400)
        PlotHold.objects.filter(plot=plot).update(released_at=timezone.now())
        payload["from_datetime"] = (now + timedelta(hours=3)).isoformat()
        payload["to_datetime"] = (now + timedelta(hours=4)).isoformat()
        self.assertEqual(self.client.post(self.operation_url(plot, "hold"), payload, format="json", **self.headers()).status_code, 200)
        invalid_range = {"reason": "Invalid", "from_datetime": (now + timedelta(hours=5)).isoformat(), "to_datetime": (now + timedelta(hours=4)).isoformat()}
        released_plot = self.plot(number="A-range")
        self.assertEqual(self.client.post(self.operation_url(released_plot, "hold"), invalid_range, format="json", **self.headers()).status_code, 400)

    def test_bulk_is_all_or_nothing_and_creates_per_plot_history(self):
        first = self.plot(number="A-bulk-1")
        second = self.plot(number="A-bulk-2")
        bulk_url = reverse("inventory:plot-bulk-status", args=[self.organization.slug])
        response = self.client.post(bulk_url, {"plot_ids": [first.id, second.id], "status": "blocked", "reason": "Project hold"}, format="json", **self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated"], 2)
        self.assertEqual(PlotStatusHistory.objects.filter(plot__in=[first, second]).count(), 2)

        invalid = self.plot(Plot.Status.SOLD, "A-bulk-sold")
        available = self.plot(number="A-bulk-available")
        response = self.client.post(bulk_url, {"plot_ids": [available.id, invalid.id], "status": "blocked", "reason": "Project hold"}, format="json", **self.headers())
        self.assertEqual(response.status_code, 400)
        available.refresh_from_db()
        self.assertEqual(available.status, Plot.Status.AVAILABLE)
        self.assertFalse(PlotStatusHistory.objects.filter(plot=available).exists())

    def test_cross_organization_operations_are_hidden_and_read_only_role_cannot_modify(self):
        foreign = self.other_plot()
        for operation in ("status", "block", "hold", "release"):
            payload = self.status_payload("blocked") if operation == "status" else {"reason": "x"}
            self.assertEqual(self.client.post(self.operation_url(foreign, operation), payload, format="json", **self.headers()).status_code, 404)
        self.assertEqual(self.client.get(reverse("inventory:plot-history", args=[self.organization.slug, foreign.id]), **self.headers()).status_code, 404)
        bulk_url = reverse("inventory:plot-bulk-status", args=[self.organization.slug])
        self.assertEqual(self.client.post(bulk_url, {"plot_ids": [foreign.id], "status": "blocked", "reason": "x"}, format="json", **self.headers()).status_code, 400)

        viewer = APIClient()
        viewer.force_authenticate(self.telecaller)
        own_plot = self.plot(number="A-viewer")
        self.assertEqual(viewer.post(self.status_url(own_plot), self.status_payload("blocked"), format="json", **self.headers()).status_code, 403)
        self.assertEqual(viewer.post(bulk_url, {"plot_ids": [own_plot.id], "status": "blocked", "reason": "x"}, format="json", **self.headers()).status_code, 403)

    def test_plot_list_requires_project_plots_view_permission(self):
        project_role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Telecaller Project Role",
            code="telecaller-project-role",
        )
        membership = OrganizationMembership.objects.get(user=self.telecaller, organization=self.organization)
        ProjectAssignment.objects.update_or_create(
            membership=membership,
            project=self.project,
            defaults={"role": project_role},
        )
        self.plot(number="A-permission")
        viewer = APIClient()
        viewer.force_authenticate(self.telecaller)
        url = reverse("inventory:plots", args=[self.organization.slug])

        denied = viewer.get(url, **self.headers())
        self.assertEqual(denied.status_code, 403)

        plots_view, _ = Permission.objects.get_or_create(
            module="plots", action="view", defaults={"name": "View plots"}
        )
        project_role.permissions.add(plots_view)
        allowed = viewer.get(url, **self.headers())
        self.assertEqual(allowed.status_code, 200, allowed.data)

    def test_plot_view_team_permission_returns_project_inventory_without_granting_edit_access(self):
        project_role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Inventory Viewer",
            code="inventory-viewer",
        )
        plots_view, _ = Permission.objects.get_or_create(
            module="plots", action="view", defaults={"name": "View plots"}
        )
        plots_view_team, _ = Permission.objects.get_or_create(
            module="plots", action="view_team", defaults={"name": "View all project plots"}
        )
        plots_edit, _ = Permission.objects.get_or_create(
            module="plots", action="edit", defaults={"name": "Edit plots"}
        )
        project_role.permissions.set([plots_view, plots_view_team])
        membership = OrganizationMembership.objects.get(user=self.telecaller, organization=self.organization)
        ProjectAssignment.objects.update_or_create(
            membership=membership,
            project=self.project,
            defaults={"role": project_role},
        )
        first = self.plot(number="A-team-1")
        second = self.plot(number="A-team-2")

        viewer = APIClient()
        viewer.force_authenticate(self.telecaller)
        url = reverse("inventory:plots", args=[self.organization.slug])

        response = viewer.get(url, **self.headers())

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({item["id"] for item in response.data["results"]}, {first.id, second.id})
        self.assertFalse(project_role.permissions.filter(pk=plots_edit.pk).exists())
