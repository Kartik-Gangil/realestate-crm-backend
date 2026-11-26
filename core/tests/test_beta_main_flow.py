from datetime import date, timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse as django_reverse
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from documents.models import CustomerDocument, CustomerDocumentRequirement, DocumentCategory
from inventory.models import Agreement, AgreementSignedDocument, Block, Payment, Plot, PlotBooking
from leads.models import Lead, Sitevisit
from system_settings.models import MasterData, MasterDataCategory


def reverse(name, args=None):
    """Exercise the canonical v1 mount even where legacy reverse names remain."""
    url = django_reverse(name, args=args)
    return url if url.startswith("/api/v1/") else url.replace("/api/", "/api/v1/", 1)


class BetaMainFlowApiTests(TestCase):
    """Beta-1 main-flow contract tests; production fixes belong to Tasks 4-7."""

    def setUp(self):
        self.organization = make_organization("demo-beta")
        self.other_project = make_project(self.organization, "OTHER")
        self.project = make_project(self.organization, "DEMO")
        self.other_org = make_organization("demo-other")
        self.other_org_project = make_project(self.other_org, "OTHER")
        self.manager_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.admin_membership = make_member(self.organization, role="admin", projects=[self.project])
        self.telecaller_membership = make_member(self.organization, role="telecaller", projects=[self.project])
        self.executive_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.other_membership = make_member(self.organization, role="manager", projects=[self.other_project])
        self.other_org_membership = make_member(self.other_org, role="manager", projects=[self.other_org_project])

        self.block = Block.objects.create(organization=self.organization, project=self.project, name="A", code="A")
        self.plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="A-001",
            size=Decimal("100.00"),
            total_price=Decimal("1000.00"),
            status=Plot.Status.AVAILABLE,
        )
        self.category = DocumentCategory.objects.create(
            organization=self.organization, name="Identity", code="identity"
        )
        MasterData.objects.get_or_create(
            organization=self.organization,
            project=self.project,
            category=MasterDataCategory.objects.get(code="payment_mode"),
            code="cash",
            defaults={"name": "Cash"},
        )
        self.client = APIClient()

    def headers(self, project=None):
        return project_request_kwargs(project or self.project)

    def use(self, user):
        self.client.force_authenticate(user)

    def post(self, user, name, payload=None, *, project=None, format="json"):
        self.use(user)
        return self.client.post(
            reverse(name, args=[self.organization.slug, *self._args_for(name, payload)]),
            payload or {},
            format=format,
            **self.headers(project),
        )

    @staticmethod
    def _args_for(name, payload):
        return []

    def test_manager_to_registry_main_flow_uses_real_v1_routes(self):
        self.use(self.manager_membership.user)
        lead_response = self.client.post(
            reverse("leads:manual-create", args=[self.organization.slug]),
            {"first_name": "Beta", "last_name": "Buyer", "phone": "9000000999", "source": "website"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(lead_response.status_code, 201, lead_response.data)
        lead_id = lead_response.data["id"]

        assign_response = self.client.patch(
            reverse("leads:assign-lead", args=[self.organization.slug, lead_id]),
            {"telecaller_membership": self.telecaller_membership.id, "reason": "Beta queue assignment"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(assign_response.status_code, 200, assign_response.data)

        self.use(self.telecaller_membership.user)
        queue = self.client.get(
            reverse("telecalling-queue", args=[self.organization.slug]), **self.headers()
        )
        self.assertEqual(queue.status_code, 200, queue.data)
        self.assertIn(lead_id, [item["id"] for item in queue.data["results"]])
        call_url = reverse("telecalling-call-log", args=[self.organization.slug])
        contacted = self.client.post(
            call_url,
            {"lead_id": lead_id, "disposition": "Busy", "status": "contacted", "notes": "warm"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(contacted.status_code, 201, contacted.data)
        qualified = self.client.post(
            call_url,
            {"lead_id": lead_id, "disposition": "Busy", "status": "qualified", "notes": "qualified"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(qualified.status_code, 201, qualified.data)

        self.use(self.manager_membership.user)
        visit = self.client.post(
            reverse("leads:site-visit", args=[self.organization.slug]),
            {
                "lead": lead_id,
                "executive": self.executive_membership.id,
                "visit_date": (date.today() + timedelta(days=1)).isoformat(),
                "visit_time": "10:00:00",
                "duration_minutes": 60,
                "site": "Beta Site",
            },
            format="json",
            **self.headers(),
        )
        self.assertEqual(visit.status_code, 201, visit.data)
        visit_id = visit.data["id"]

        self.use(self.executive_membership.user)
        in_progress = self.client.patch(
            reverse("leads:site-visit-detail", args=[self.organization.slug, visit_id]),
            {"status": "in_progress"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(in_progress.status_code, 200, in_progress.data)
        outcome = self.client.post(
            reverse("leads:site-visit-outcome", args=[self.organization.slug, visit_id]),
            {"outcome": "interested", "interest_level": 5},
            format="json",
            **self.headers(),
        )
        self.assertEqual(outcome.status_code, 200, outcome.data)

        self.use(self.manager_membership.user)
        hold = self.client.post(
            reverse("inventory:plot-hold", args=[self.organization.slug, self.plot.id]),
            {"reason": "Beta flow"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(hold.status_code, 200, hold.data)
        release = self.client.post(
            reverse("inventory:plot-release", args=[self.organization.slug, self.plot.id]),
            {"reason": "Convert temporary hold into booking hold"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(release.status_code, 200, release.data)
        booking = self.client.post(
            reverse("inventory:bookings", args=[self.organization.slug]),
            {"lead_id": lead_id, "plot_id": self.plot.id, "site_visit_id": visit_id, "notes": "Beta"},
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="beta-main-booking-1",
            **self.headers(),
        )
        self.assertEqual(booking.status_code, 201, booking.data)
        booking_id = booking.data["id"]

        confirm_url = reverse("inventory:booking-confirm", args=[self.organization.slug, booking_id])
        missing_identity = self.client.post(confirm_url, {}, format="json", **self.headers())
        self.assertEqual(missing_identity.status_code, 400, missing_identity.data)

        CustomerDocumentRequirement.objects.create(
            organization=self.organization,
            customer_id=lead_id,
            document_category=self.category,
            is_mandatory=True,
        )
        document = self.client.post(
            reverse("documents:list", args=[self.organization.slug]),
            {
                "customer": lead_id,
                "document_category": self.category.id,
                "document_name": "Identity",
                "file": SimpleUploadedFile("identity.pdf", b"%PDF-1.4 beta", content_type="application/pdf"),
            },
            format="multipart",
            **self.headers(),
        )
        self.assertEqual(document.status_code, 201, document.data)
        document_id = document.data["id"]
        self.assertEqual(
            self.client.post(
                reverse("documents:under-verification", args=[self.organization.slug, document_id]),
                {},
                format="json",
                **self.headers(),
            ).status_code,
            200,
        )
        verified = self.client.post(
            reverse("documents:verify", args=[self.organization.slug, document_id]),
            {},
            format="json",
            **self.headers(),
        )
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertEqual(self.client.post(confirm_url, {}, format="json", **self.headers()).status_code, 200)

        payment = self.client.post(
            reverse("inventory:booking-payments", args=[self.organization.slug, booking_id]),
            {"amount": "100.00", "payment_method": "cash", "payment_date": date.today().isoformat()},
            format="json",
            **self.headers(),
        )
        self.assertEqual(payment.status_code, 201, payment.data)
        payment_id = payment.data["id"]
        self.assertEqual(
            self.client.post(
                reverse("inventory:payment-confirm", args=[self.organization.slug, payment_id]),
                {},
                format="json",
                **self.headers(),
            ).status_code,
            200,
        )
        payment_detail_url = reverse("inventory:payment-detail", args=[self.organization.slug, payment_id])
        self.assertEqual(self.client.patch(payment_detail_url, {"amount": "999.00"}, format="json", **self.headers()).status_code, 405)
        self.assertEqual(self.client.delete(payment_detail_url, **self.headers()).status_code, 405)
        ledger = self.client.get(
            reverse("inventory:customer-payment-ledger", args=[self.organization.slug, lead_id]),
            **self.headers(),
        )
        self.assertEqual(ledger.status_code, 200, ledger.data)
        self.assertTrue(ledger.data["entries"])
        self.assertEqual(ledger.data["entries"][0]["particulars"], f"Payment #{ledger.data['entries'][0]['reference']}")
        self.assertEqual(ledger.data["entries"][0]["balance"], ledger.data["current_outstanding"])
        self.use(self.telecaller_membership.user)
        self.assertEqual(
            self.client.post(
                reverse("inventory:payment-refund", args=[self.organization.slug, payment_id]),
                {"amount": "10.00", "reason": "No"},
                format="json",
                **self.headers(),
            ).status_code,
            403,
        )

        self.use(self.manager_membership.user)
        agreement = self.client.post(
            reverse("inventory:booking-agreement", args=[self.organization.slug, booking_id]),
            {},
            format="json",
            **self.headers(),
        )
        self.assertEqual(agreement.status_code, 201, agreement.data)
        agreement_id = agreement.data["id"]
        self.assertEqual(
            self.client.post(
                reverse("inventory:agreement-ready", args=[self.organization.slug, agreement_id]),
                {},
                format="json",
                **self.headers(),
            ).status_code,
            200,
        )
        signed = self.client.post(
            reverse("inventory:agreement-upload-signed", args=[self.organization.slug, agreement_id]),
            {"file": SimpleUploadedFile("signed.pdf", b"%PDF-1.4 signed", content_type="application/pdf")},
            format="multipart",
            **self.headers(),
        )
        self.assertEqual(signed.status_code, 201, signed.data)
        self.assertEqual(
            self.client.post(
                reverse("inventory:agreement-sign", args=[self.organization.slug, agreement_id]),
                {},
                format="json",
                **self.headers(),
            ).status_code,
            200,
        )
        open_registry = self.client.post(
            reverse("inventory:booking-registry", args=[self.organization.slug, booking_id]),
            {"registry_number": "BETA-1", "registry_date": date.today().isoformat()},
            format="json",
            **self.headers(),
        )
        self.assertEqual(open_registry.status_code, 201, open_registry.data)
        registry_id = open_registry.data["id"]
        self.assertEqual(
            self.client.post(
                reverse("inventory:registry-schedule", args=[self.organization.slug, registry_id]),
                {},
                format="json",
                **self.headers(),
            ).status_code,
            200,
        )
        open_dues_completion = self.client.post(
            reverse("inventory:registry-complete", args=[self.organization.slug, registry_id]),
            {},
            format="json",
            **self.headers(),
        )
        self.assertEqual(open_dues_completion.status_code, 400, open_dues_completion.data)

        remaining_payment = self.client.post(
            reverse("inventory:booking-payments", args=[self.organization.slug, booking_id]),
            {"amount": "900.00", "payment_method": "cash", "payment_date": date.today().isoformat()},
            format="json",
            **self.headers(),
        )
        self.assertEqual(remaining_payment.status_code, 201, remaining_payment.data)
        self.assertEqual(
            self.client.post(
                reverse("inventory:payment-confirm", args=[self.organization.slug, remaining_payment.data["id"]]),
                {},
                format="json",
                **self.headers(),
            ).status_code,
            200,
        )

        completed = self.client.post(
            reverse("inventory:registry-complete", args=[self.organization.slug, registry_id]),
            {},
            format="json",
            **self.headers(),
        )
        self.assertEqual(completed.status_code, 200, completed.data)
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, Plot.Status.SOLD)

    def test_plot_hold_cannot_be_booked_by_another_user(self):
        lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Other Hold Buyer",
            phone="9000000777",
        )
        self.use(self.manager_membership.user)
        hold = self.client.post(
            reverse("inventory:plot-hold", args=[self.organization.slug, self.plot.id]),
            {"reason": "Lead-specific temporary hold"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(hold.status_code, 200, hold.data)

        self.use(self.executive_membership.user)
        booking = self.client.post(
            reverse("inventory:bookings", args=[self.organization.slug]),
            {"lead_id": lead.id, "plot_id": self.plot.id, "notes": "Other user"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(booking.status_code, 400, booking.data)

    def test_plot_hold_owner_can_create_pending_booking(self):
        lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Hold Owner Buyer",
            phone="9000000788",
            lifecycle_status="site_visit_completed",
        )
        self.use(self.manager_membership.user)
        hold = self.client.post(
            reverse("inventory:plot-hold", args=[self.organization.slug, self.plot.id]),
            {"reason": "Convert owner hold into booking"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(hold.status_code, 200, hold.data)

        booking = self.client.post(
            reverse("inventory:bookings", args=[self.organization.slug]),
            {"lead_id": lead.id, "plot_id": self.plot.id, "notes": "Owner hold booking"},
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="beta-hold-owner-booking-1",
            **self.headers(),
        )
        self.assertEqual(booking.status_code, 201, booking.data)
        self.assertEqual(booking.data["status"], PlotBooking.Status.PENDING)

    def test_telecaller_cannot_jump_new_lead_directly_to_qualified(self):
        self.use(self.manager_membership.user)
        lead_response = self.client.post(
            reverse("leads:manual-create", args=[self.organization.slug]),
            {"first_name": "Jump", "phone": "9000000888", "source": "website"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(lead_response.status_code, 201, lead_response.data)
        lead_id = lead_response.data["id"]
        self.assertEqual(
            self.client.patch(
                reverse("leads:assign-lead", args=[self.organization.slug, lead_id]),
                {"telecaller_membership": self.telecaller_membership.id, "reason": "Beta illegal-jump fixture assignment"},
                format="json",
                **self.headers(),
            ).status_code,
            200,
        )
        self.use(self.telecaller_membership.user)
        response = self.client.post(
            reverse("telecalling-call-log", args=[self.organization.slug]),
            {"lead_id": lead_id, "disposition": "Busy", "status": "qualified", "notes": "jump"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_manager_can_request_refund_but_only_admin_can_approve_p11(self):
        lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Refund",
            last_name="Requester",
            phone="9000000889",
            source="website",
        )
        booking = PlotBooking.objects.create(
            organization=self.organization,
            lead=lead,
            plot=self.plot,
            status=PlotBooking.Status.CONFIRMED,
            final_price=Decimal("1000.00"),
            created_by=self.manager_membership.user,
        )
        self.plot.status = Plot.Status.BOOKED
        self.plot.save(update_fields=["status", "updated_at"])
        payment = Payment.objects.create(
            organization=self.organization,
            booking=booking,
            amount=Decimal("500.00"),
            payment_method=Payment.Method.CASH,
            status=Payment.Status.SUCCESS,
            payment_date=date.today(),
            received_by=self.manager_membership.user,
        )
        request_url = reverse("inventory:managed-payment-refund", args=[self.organization.slug, payment.id])
        self.use(self.manager_membership.user)
        requested = self.client.post(
            request_url,
            {"amount": "100.00", "reason": "Customer request", "refund_date": date.today().isoformat()},
            format="json",
            **self.headers(),
        )
        self.assertEqual(requested.status_code, 201, requested.data)
        refund_id = requested.data["id"]

        approve_url = reverse(
            "inventory:managed-payment-refund-approve",
            args=[self.organization.slug, payment.id, refund_id],
        )
        refused = self.client.post(approve_url, {"action": "approve"}, format="json", **self.headers())
        self.assertEqual(refused.status_code, 403, refused.data)

        self.use(self.admin_membership.user)
        approved = self.client.post(approve_url, {"action": "approve"}, format="json", **self.headers())
        self.assertEqual(approved.status_code, 200, approved.data)

    def test_registry_completion_rejects_open_dues(self):
        lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Dues",
            phone="9000000777",
            source="website",
        )
        CustomerDocument.objects.create(
            organization=self.organization,
            customer=lead,
            document_category=self.category,
            document_name="Identity",
            file=SimpleUploadedFile("identity.pdf", b"%PDF-1.4 verified", content_type="application/pdf"),
            file_name="identity.pdf",
            file_size=16,
            content_type="application/pdf",
            version=1,
            status=CustomerDocument.Status.VERIFIED,
        )
        booking = PlotBooking.objects.create(
            organization=self.organization,
            lead=lead,
            plot=self.plot,
            status=PlotBooking.Status.CONFIRMED,
            final_price=Decimal("1000.00"),
            created_by=self.manager_membership.user,
        )
        self.plot.status = Plot.Status.BOOKED
        self.plot.save(update_fields=["status", "updated_at"])
        agreement = Agreement.objects.create(
            organization=self.organization,
            booking=booking,
            status=Agreement.Status.SIGNED,
            created_by=self.manager_membership.user,
        )
        AgreementSignedDocument.objects.create(
            agreement=agreement,
            file=SimpleUploadedFile("signed.pdf", b"%PDF-1.4 signed", content_type="application/pdf"),
            original_filename="signed.pdf",
            content_type="application/pdf",
            file_size_bytes=16,
            uploaded_by=self.manager_membership.user,
        )

        self.use(self.manager_membership.user)
        registry = self.client.post(
            reverse("inventory:booking-registry", args=[self.organization.slug, booking.id]),
            {"registry_number": "BETA-DUES", "registry_date": date.today().isoformat()},
            format="json",
            **self.headers(),
        )
        self.assertEqual(registry.status_code, 201, registry.data)
        registry_id = registry.data["id"]
        scheduled = self.client.post(
            reverse("inventory:registry-schedule", args=[self.organization.slug, registry_id]),
            {},
            format="json",
            **self.headers(),
        )
        self.assertEqual(scheduled.status_code, 200, scheduled.data)
        response = self.client.post(
            reverse("inventory:registry-complete", args=[self.organization.slug, registry_id]),
            {},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_every_main_flow_step_rejects_other_project_context(self):
        self.use(self.other_membership.user)
        headers = self.headers(self.other_project)
        lead_list = self.client.get(reverse("leads:list", args=[self.organization.slug]), **headers)
        self.assertEqual(lead_list.status_code, 200, lead_list.data)
        self.assertEqual(lead_list.data["results"], [])
        queue = self.client.get(reverse("telecalling-queue", args=[self.organization.slug]), **headers)
        self.assertIn(queue.status_code, {200, 403}, queue.data)
        if queue.status_code == 200:
            self.assertEqual(queue.data["results"], [])
        checks = [
            self.client.post(
                reverse("inventory:plot-hold", args=[self.organization.slug, self.plot.id]),
                {"reason": "cross project"},
                format="json",
                **headers,
            ),
            self.client.get(
                reverse("inventory:booking-detail", args=[self.organization.slug, self.plot.id]), **headers
            ),
        ]
        for response in checks:
            self.assertIn(response.status_code, {403, 404}, response.data)

