from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import OperationalError, close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from core.exceptions import is_database_busy_error
from documents.models import CustomerDocument, DocumentCategory
from inventory.models import Block, BookingIdempotencyKey, BookingReceiptSequence, Customer, Payment, PaymentAllocation, PaymentReceipt, Plot, PlotBooking
from inventory.phase5_services import payment_totals
from inventory.services import create_idempotent_booking
from leads.models import Lead, Sitevisit
from organizations.services import ensure_default_roles
from system_settings.models import MasterData, MasterDataCategory
from system_settings.parameters import PARAMETER_REGISTRY

from . import views


class GroupBBookingFixTests(TestCase):
    """Task 8 / FR-P9-03/04/06/07/08/09/10 and NFR-P9-01/02/03."""

    def setUp(self):
        self.organization = make_organization("group-b-fix")
        self.project = make_project(self.organization, "GBF")
        self.block = Block.objects.create(
            organization=self.organization, project=self.project, name="Block A", code="A"
        )
        self.manager_membership = make_member(
            self.organization, role="manager", projects=[self.project]
        )
        self.manager = self.manager_membership.user
        self.lead = self.make_lead("Eligible", "site_visit_completed")
        self.visit = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            executive_membership=self.manager_membership,
            site="Group B site",
            status=Sitevisit.Status.COMPLETED,
        )
        MasterData.objects.get_or_create(
            organization=self.organization,
            project=self.project,
            category=MasterDataCategory.objects.get(code="payment_mode"),
            code="upi",
            defaults={"name": "UPI", "is_active": True},
        )

    def make_lead(self, first_name, lifecycle_status):
        return Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name=first_name,
            last_name="Lead",
            phone=f"900000{Lead.objects.count() + 2000:04d}",
            lifecycle_status=lifecycle_status,
        )

    def make_plot(self, number, total="1000.00"):
        return Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number=number,
            size=Decimal("100"),
            total_price=Decimal(total),
        )

    def create_booking(self, plot, *, key, amount="0", payment_mode="upi", reference="UPI-REF"):
        return create_idempotent_booking(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            plot=plot,
            user=self.manager,
            idempotency_key=key,
            body={
                "lead_id": self.lead.pk,
                "plot_id": plot.pk,
                "initial_payment": amount,
                "payment_mode": payment_mode,
                "transaction_reference": reference,
            },
            site_visit=self.visit,
            initial_payment=amount,
            payment_mode=payment_mode,
            transaction_reference=reference,
        )

    def test_fr_p9_06_registers_minimum_payment_parameter(self):
        parameter = PARAMETER_REGISTRY["booking_minimum_payment_percent"]
        self.assertEqual((parameter.scope, parameter.default, parameter.min_value, parameter.max_value), ("project", 10, 0, 100))

    def test_fr_p9_04_full_payment_remains_partially_paid_and_stores_mode_reference(self):
        booking = self.create_booking(self.make_plot("A-1"), key="full-payment", amount="1000.00")
        payment = Payment.objects.get(booking=booking)
        self.assertEqual(booking.status, PlotBooking.Status.PARTIALLY_PAID)
        self.assertEqual(payment.payment_method, "upi")
        self.assertEqual(payment.transaction_reference, "UPI-REF")

    def test_fr_p9_01_invalid_payment_mode_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create_booking(self.make_plot("A-2"), key="bad-mode", amount="10", payment_mode="cash")

    def test_fr_p9_03_initial_payment_is_allocated_receipted_and_in_customer_ledger(self):
        booking = self.create_booking(self.make_plot("LEDGER"), key="ledger", amount="1000")
        payment = Payment.objects.get(booking=booking)
        self.assertEqual(PaymentAllocation.objects.get(payment=payment).amount, Decimal("1000"))
        self.assertTrue(PaymentReceipt.objects.filter(payment=payment).exists())
        self.assertEqual(payment_totals(booking)["net_paid"], Decimal("1000"))
        PlotBooking.objects.filter(pk=booking.pk).update(status=PlotBooking.Status.CONFIRMED)
        client = APIClient()
        client.force_authenticate(self.manager)
        response = client.get(
            reverse("inventory:customer-payment-ledger", args=[self.organization.slug, self.lead.pk]),
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["entries"][0]["reference"], payment.payment_id)
        self.assertEqual(Decimal(response.data["current_outstanding"]), Decimal("0"))
        from inventory.models import Registry
        from inventory.phase5_services import transition_registry

        registry = Registry.objects.create(
            organization=self.organization, booking=booking, registry_date=timezone.localdate(),
            status=Registry.Status.SCHEDULED,
        )
        with patch("documents.services.validate_customer_documents_for_booking", return_value={"allowed": True}):
            transition_registry(registry=registry, status=Registry.Status.COMPLETED, user=self.manager)
        registry.refresh_from_db()
        self.assertEqual(registry.status, Registry.Status.COMPLETED)

    def test_fr_p9_06_ec_p9_01_worker_expires_zero_and_below_minimum_but_not_at_minimum(self):
        zero = self.create_booking(self.make_plot("A-3"), key="zero", amount="0")
        below = self.create_booking(self.make_plot("A-4"), key="below", amount="50")
        minimum = self.create_booking(self.make_plot("A-5"), key="minimum", amount="100")
        old = timezone.now() - timedelta(days=1)
        PlotBooking.objects.filter(pk__in=[zero.pk, below.pk, minimum.pk]).update(hold_expires_at=old)
        PlotBooking.objects.filter(pk=minimum.pk).update(booking_amount_paid=0)
        PlotBooking.objects.filter(pk=below.pk).update(booking_amount_paid=1000)
        from core.tasks_backend import process_due_bookings

        process_due_bookings()
        zero.refresh_from_db(); below.refresh_from_db(); minimum.refresh_from_db()
        self.assertEqual(zero.status, PlotBooking.Status.EXPIRED)
        self.assertEqual(below.status, PlotBooking.Status.EXPIRED)
        self.assertEqual(minimum.status, PlotBooking.Status.PARTIALLY_PAID)

    def test_fr_p9_07_confirmed_booking_never_expires(self):
        booking = self.create_booking(self.make_plot("A-6"), key="confirmed", amount="100")
        PlotBooking.objects.filter(pk=booking.pk).update(status=PlotBooking.Status.CONFIRMED, hold_expires_at=timezone.now() - timedelta(days=1))
        from core.tasks_backend import process_due_bookings

        process_due_bookings()
        booking.refresh_from_db()
        self.assertEqual(booking.status, PlotBooking.Status.CONFIRMED)

    def test_fr_p9_09_plot_view_only_cannot_book(self):
        access = SimpleNamespace(
            is_platform=False,
            membership=self.manager_membership,
            organization=self.organization,
            project=self.project,
        )
        with patch.object(views, "has_permission", side_effect=lambda *args, **kwargs: args[2] == "plots.view"):
            with self.assertRaises(PermissionDenied):
                views._require_booking_creation(access)

    def test_fr_p9_09_non_completed_lead_statuses_are_refused(self):
        for status in ("interested", "site_visit_scheduled", "lost", "converted"):
            with self.subTest(status=status):
                lead = self.make_lead(status.title(), status)
                with self.assertRaises(ValidationError):
                    create_idempotent_booking(
                        organization=self.organization,
                        project=self.project,
                        lead=lead,
                        plot=self.make_plot(f"S-{status}"),
                        user=self.manager,
                        idempotency_key=f"status-{status}",
                        site_visit=self.visit,
                    )

    def test_fr_p9_09_role_scopes_allow_only_their_leads_or_executed_visits(self):
        from inventory.views import _require_booking_lead_scope

        telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        other_telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        telecaller_lead = self.make_lead("Telecaller", "site_visit_completed")
        telecaller_lead.assigned_membership = telecaller
        telecaller_lead.save(update_fields=["assigned_membership"])
        access = SimpleNamespace(is_platform=False, membership=telecaller, organization=self.organization, project=self.project)
        _require_booking_lead_scope(access, telecaller_lead, self.visit)
        telecaller_lead.assigned_membership = other_telecaller
        telecaller_lead.save(update_fields=["assigned_membership"])
        with self.assertRaises(PermissionDenied):
            _require_booking_lead_scope(access, telecaller_lead, self.visit)

        executive = make_member(self.organization, role="site-visit-executive", projects=[self.project])
        executed_visit = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=telecaller_lead,
            executive_membership=executive,
            site="Group B site",
            status=Sitevisit.Status.COMPLETED,
        )
        executive_access = SimpleNamespace(is_platform=False, membership=executive, organization=self.organization, project=self.project)
        _require_booking_lead_scope(executive_access, telecaller_lead, executed_visit)
        with self.assertRaises(PermissionDenied):
            _require_booking_lead_scope(executive_access, telecaller_lead, self.visit)

    def test_nfr_p9_01_each_booking_step_rolls_back_all_rows_and_sequences(self):
        from inventory import services

        failure_points = (
            "_customer_for_booking",
            "_booking_receipt_number",
            "plot_booking_create",
            "change_plot_status",
            "payment_create",
            "idempotency_create",
        )
        for index, failure_point in enumerate(failure_points, start=20):
            plot = self.make_plot(f"F-{index}")
            before_sequence = BookingReceiptSequence.objects.filter(project=self.project).values_list("next_number", flat=True).first()
            patches = []
            if failure_point == "_customer_for_booking":
                patches.append(patch.object(services, "_customer_for_booking", side_effect=ValidationError({"step": failure_point})))
            elif failure_point == "_booking_receipt_number":
                patches.append(patch.object(services, "_booking_receipt_number", side_effect=ValidationError({"step": failure_point})))
            elif failure_point == "plot_booking_create":
                patches.append(patch.object(PlotBooking.objects, "create", side_effect=ValidationError({"step": failure_point})))
            elif failure_point == "change_plot_status":
                patches.append(patch.object(services, "change_plot_status", side_effect=ValidationError({"step": failure_point})))
            elif failure_point == "payment_create":
                patches.append(patch.object(Payment.objects, "create", side_effect=ValidationError({"step": failure_point})))
            else:
                patches.append(patch.object(BookingIdempotencyKey.objects, "create", side_effect=ValidationError({"step": failure_point})))
            with patches[0], self.assertRaises(ValidationError):
                self.create_booking(plot, key=f"forced-{failure_point}", amount="100", reference=f"REF-{index}")
            self.assertFalse(PlotBooking.objects.filter(plot=plot).exists(), failure_point)
            self.assertFalse(Customer.objects.filter(lead=self.lead).exists(), failure_point)
            self.assertFalse(Payment.objects.filter(booking__plot=plot).exists(), failure_point)
            self.assertFalse(PaymentAllocation.objects.filter(booking__plot=plot).exists(), failure_point)
            self.assertEqual(Plot.objects.get(pk=plot.pk).status, Plot.Status.AVAILABLE)
            after_sequence = BookingReceiptSequence.objects.filter(project=self.project).values_list("next_number", flat=True).first()
            self.assertEqual(after_sequence, before_sequence, failure_point)

    def test_fr_p9_10_confirm_requires_verified_identity_and_moves_lead_to_converted(self):
        booking = self.create_booking(self.make_plot("A-7"), key="confirm-gate")
        from inventory.services import confirm_plot_booking

        with self.assertRaises(Exception):
            confirm_plot_booking(booking=booking, user=self.manager)
        category = DocumentCategory.objects.create(organization=self.organization, name="Identity", code="identity")
        document = CustomerDocument.objects.create(
            organization=self.organization,
            customer=booking.customer,
            document_category=category,
            document_name="Identity",
            file="documents/test.pdf",
            file_name="test.pdf",
            file_size=1,
            content_type="application/pdf",
            version=1,
            status=CustomerDocument.Status.VERIFIED,
            verified_by=self.manager,
        )
        document.save()
        confirmed = confirm_plot_booking(booking=booking, user=self.manager)
        self.assertEqual(confirmed.status, PlotBooking.Status.CONFIRMED)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.lifecycle_status, "converted")


class GroupBBookingApiContractTests(TestCase):
    """Task 8 / API-P9-02 and NFR-P9-03 endpoint-level idempotency tests."""

    def setUp(self):
        self.organization = make_organization("group-b-api")
        self.project = make_project(self.organization, "GBA")
        self.block = Block.objects.create(organization=self.organization, project=self.project, name="A", code="A")
        self.member = make_member(self.organization, role="manager", projects=[self.project])
        self.lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="API",
            last_name="Lead",
            phone="9000003001",
            lifecycle_status="site_visit_completed",
        )
        self.plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="A-1",
            size=Decimal("100"),
            total_price=Decimal("1000"),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.member.user)

    def payload(self):
        return {"lead_id": self.lead.pk, "plot_id": self.plot.pk, "initial_payment": "0"}

    def headers(self):
        return project_request_kwargs(self.project)

    def url(self):
        return reverse("inventory:bookings", args=[self.organization.slug])

    def test_api_missing_key_returns_400(self):
        response = self.client.post(self.url(), self.payload(), format="json", **self.headers())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlotBooking.objects.count(), 0)

    def test_api_same_key_replays_and_different_body_conflicts(self):
        first = self.client.post(self.url(), self.payload(), format="json", HTTP_X_IDEMPOTENCY_KEY="api-key", **self.headers())
        replay = self.client.post(self.url(), self.payload(), format="json", HTTP_X_IDEMPOTENCY_KEY="api-key", **self.headers())
        conflict = self.client.post(self.url(), {**self.payload(), "initial_payment": "1"}, format="json", HTTP_X_IDEMPOTENCY_KEY="api-key", **self.headers())
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(replay.status_code, 201, replay.data)
        self.assertEqual(replay.data["id"], first.data["id"])
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(PlotBooking.objects.count(), 1)


class GroupBHoldConcurrencyTests(TransactionTestCase):
    """Task 7/8 concurrency contracts; unexpected exceptions must fail the test."""

    reset_sequences = True

    def test_nfr_p8_01_only_expected_rejections_are_counted(self):
        from inventory.services import hold_plot

        organization = make_organization("group-b-concurrency")
        project = make_project(organization, "GBC")
        block = Block.objects.create(organization=organization, project=project, name="A", code="A")
        member = make_member(organization, role="manager", projects=[project])
        plot = Plot.objects.create(organization=organization, project=project, block=block, plot_number="A-1", size=Decimal("100"))

        def attempt(index):
            close_old_connections()
            try:
                hold_plot(plot=plot, reason=f"parallel-{index}", user=member.user)
                return "success"
            except ValidationError:
                return "validation"
            except Exception as error:
                if (
                    getattr(error, "code", None) == "database_busy"
                    or getattr(error, "status_code", None) == 503
                    or (isinstance(error, OperationalError) and is_database_busy_error(error))
                ):
                    return "database_busy"
                raise
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=50) as executor:
            results = list(executor.map(attempt, range(50)))
        self.assertEqual(results.count("success"), 1)
        self.assertEqual(results.count("validation") + results.count("database_busy"), 49)


class GroupBBookingConcurrencyContractTests(TransactionTestCase):
    """NFR-P9-01/02: concurrent idempotent booking requests serialize safely."""

    reset_sequences = True

    def race(self, *, distinct_plots=False, hold=False):
        from organizations.models import Permission

        for module, action in (("plots", "book"), ("plots", "hold"), ("plots", "view_team"), ("leads", "view_team")):
            Permission.objects.get_or_create(module=module, action=action, defaults={"name": action})
        organization = make_organization("group-b-race")
        project = make_project(organization, "RACE")
        block = Block.objects.create(organization=organization, project=project, name="A", code="A")
        members = [make_member(organization, role="manager", projects=[project]) for _ in range(2)]
        leads = [
            Lead.objects.create(organization=organization, project=project, first_name="Race",
                                phone=f"900000450{i}", lifecycle_status="site_visit_completed",
                                assigned_membership=members[i])
            for i in range(2)
        ]
        plots = [
            Plot.objects.create(organization=organization, project=project, block=block,
                                plot_number=f"A-{i}", size=100, total_price=1000)
            for i in range(2 if distinct_plots else 1)
        ]
        start = Barrier(2, timeout=10)

        def attempt(i, *, synchronize=True):
            if synchronize:
                close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(members[i].user)
                headers = project_request_kwargs(project)
                if synchronize:
                    start.wait()
                if hold and i == 1:
                    return client.post(reverse("inventory-v1:plot-hold", args=[organization.slug, plots[0].pk]),
                                       {"reason": "Race hold"}, format="json", **headers)
                plot = plots[i if distinct_plots else 0]
                return client.post(
                    reverse("inventory-v1:bookings", args=[organization.slug]),
                    {"lead_id": leads[i].pk, "plot_id": plot.pk}, format="json",
                    HTTP_X_IDEMPOTENCY_KEY=f"race-{i}", **headers,
                )
            finally:
                if synchronize:
                    close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(attempt, range(2)))
        if distinct_plots:
            from django.db import connection

            if connection.vendor == "sqlite":
                for index, response in enumerate(responses):
                    if response.status_code == 503:
                        payload = response.json()
                        self.assertEqual(payload["error"]["code"], "database_busy", payload)
                        responses[index] = attempt(index, synchronize=False)
        return responses

    def test_fr_p9_05_different_keys_cannot_book_one_plot_twice(self):
        responses = self.race()
        self.assertEqual(sum(r.status_code == 201 for r in responses), 1)
        self.assertIn(next(r.status_code for r in responses if r.status_code != 201), (409, 503))
        self.assertEqual(PlotBooking.objects.count(), 1)

    def test_nfr_p9_02_parallel_bookings_allocate_consecutive_receipts(self):
        responses = self.race(distinct_plots=True)
        self.assertEqual([r.status_code for r in responses], [201, 201], [r.json() for r in responses])
        self.assertEqual(sorted(r.json()["data"]["booking_receipt_number"] for r in responses),
                         ["RACE-BR-000001", "RACE-BR-000002"])

    def test_ec_p8_01_hold_and_booking_have_one_winner(self):
        responses = self.race(hold=True)
        self.assertEqual(sum(r.status_code in (200, 201) for r in responses), 1)
        self.assertIn(next(r.status_code for r in responses if r.status_code not in (200, 201)), (409, 503))

    def test_two_parallel_requests_with_same_key_create_one_booking(self):
        from inventory.services import create_idempotent_booking

        organization = make_organization("group-b-booking-concurrency")
        project = make_project(organization, "GBC2")
        block = Block.objects.create(organization=organization, project=project, name="A", code="A")
        member = make_member(organization, role="manager", projects=[project])
        lead = Lead.objects.create(
            organization=organization,
            project=project,
            first_name="Concurrent",
            last_name="Lead",
            phone="9000003999",
            lifecycle_status="site_visit_completed",
        )
        visit = Sitevisit.objects.create(
            organization=organization,
            project=project,
            lead=lead,
            executive_membership=member,
            site="Concurrent site",
            status=Sitevisit.Status.COMPLETED,
        )
        plot = Plot.objects.create(organization=organization, project=project, block=block, plot_number="A-1", size=Decimal("100"), total_price=Decimal("1000"))
        payment_category, _ = MasterDataCategory.objects.get_or_create(
            code="payment_mode",
            defaults={"name": "Payment mode", "is_system": True},
        )
        MasterData.objects.get_or_create(
            organization=organization,
            project=project,
            category=payment_category,
            code="upi",
            defaults={"name": "UPI", "is_active": True},
        )

        def attempt():
            close_old_connections()
            try:
                return create_idempotent_booking(
                    organization=organization,
                    project=project,
                    lead=lead,
                    plot=plot,
                    user=member.user,
                    idempotency_key="parallel-booking",
                    body={"lead_id": lead.pk, "plot_id": plot.pk, "initial_payment": "0"},
                    site_visit=visit,
                )
            except (ValidationError, OperationalError):
                return None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: attempt(), range(2)))
        self.assertEqual(PlotBooking.objects.filter(plot=plot).count(), 1)
        self.assertEqual(BookingIdempotencyKey.objects.filter(key="parallel-booking").count(), 1)
        self.assertEqual(sum(result is not None for result in results), 1)
