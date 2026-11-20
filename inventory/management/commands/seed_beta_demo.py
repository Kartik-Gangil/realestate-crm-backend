import secrets
from datetime import date
from decimal import Decimal
from pathlib import Path

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from documents.models import DocumentCategory
from expenses.models import Expense, ExpenseCategory
from inventory.models import Block, Payment, PaymentReceipt, PaymentRefund, Plot, PlotBooking, Project
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership, Permission, ProjectAssignment
from organizations.services import ensure_default_roles
from system_settings.integrations import encrypt_secret
from system_settings.models import IntegrationConfiguration, MasterData, MasterDataCategory, SystemParameter
from system_settings.parameters import PARAMETER_REGISTRY


DEMO_LEADS = (
    ("Asha", "Mehta", "asha.demo.invalid", "9000000001", "website"),
    ("Rohan", "Shah", "rohan.demo.invalid", "9000000002", "fb"),
    ("Neha", "Patel", "neha.demo.invalid", "9000000003", "walk_in"),
    ("Kabir", "Joshi", "kabir.demo.invalid", "9000000004", "google"),
    ("Isha", "Nair", "isha.demo.invalid", "9000000005", "other"),
)

DEMO_ROLES = (
    ("admin", "Admin"),
    ("manager", "Manager"),
    ("telecaller", "Telecaller"),
    ("site-visit-executive", "Site Visit Executive"),
)


class Command(BaseCommand):
    help = "Create or reuse demo-only beta data in a demo-* organization."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True)
        parser.add_argument("--project", required=True)
        parser.add_argument("--with-extended-fixtures", action="store_true")

    def handle(self, *args, **options):
        organization_slug = options["organization"]
        project_code = options["project"]
        if not organization_slug.startswith("demo-"):
            raise CommandError("seed_beta_demo only accepts organization slugs starting with demo-.")
        self._validate_encryption_key()
        password_path = Path.home() / "crm-beta-demo-passwords.txt"
        with transaction.atomic():
            organization, organization_created = Organization.objects.get_or_create(
                slug=organization_slug,
                defaults={"name": "Beta Demo Organization", "is_active": True},
            )
            project, project_created = Project.objects.get_or_create(
                organization=organization,
                code=project_code,
                defaults={"name": "Beta Demo Project", "description": "Demo-only beta data."},
            )
            self._seed_master_data(organization, project)
            self._seed_document_categories(organization)
            roles = ensure_default_roles(organization)
            self._ensure_manager_site_visit_permissions(roles["manager"])
            memberships, new_passwords = self._seed_users(organization, project, roles)
            self._seed_plots(organization, project, created_by=memberships[3].user)
            self._seed_leads(organization, project)
            self._seed_parameters(organization, project)
            self._seed_integrations(organization)
            if options["with_extended_fixtures"]:
                self._seed_extended_fixtures(organization, project, memberships)

        if new_passwords:
            self._write_password_file(password_path, new_passwords)
        self.stdout.write(
            self.style.SUCCESS(
                "Beta demo ready: "
                f"organization={'created' if organization_created else 'reused'}, "
                f"project={'created' if project_created else 'reused'}, "
                f"users={len(memberships)}, leads={len(DEMO_LEADS)}, plots=20, "
                f"credentials_file={password_path}"
            )
        )

    @staticmethod
    def _validate_encryption_key():
        from django.conf import settings

        key = (settings.INTEGRATION_ENCRYPTION_KEY or "").strip()
        if not key:
            raise CommandError("INTEGRATION_ENCRYPTION_KEY must be a valid Fernet key before creating integrations.")
        try:
            Fernet(key.encode())
        except (ValueError, TypeError) as error:
            raise CommandError("INTEGRATION_ENCRYPTION_KEY must be a valid Fernet key before creating integrations.") from error

    @staticmethod
    def _seed_master_data(organization, project):
        definitions = {
            "lead_stage": (("new", "New"), ("contacted", "Contacted"), ("qualified", "Qualified"), ("site_visit", "Site Visit"), ("won", "Won"), ("lost", "Lost")),
            "lead_source": (("website", "Website"), ("fb", "Facebook"), ("ig", "Instagram"), ("site_visit", "Site Visit"), ("walk_in", "Walk-in"), ("other", "Other"), ("google", "Google")),
            "payment_mode": (("cash", "Cash"), ("upi", "UPI"), ("card", "Card"), ("net_banking", "Net Banking"), ("cheque", "Cheque"), ("wallet", "Wallet")),
        }
        for category_code, values in definitions.items():
            category, _ = MasterDataCategory.objects.get_or_create(
                code=category_code,
                defaults={"name": category_code.replace("_", " ").title(), "is_system": True},
            )
            for sort_order, (code, name) in enumerate(values):
                default, _ = MasterData.objects.get_or_create(
                    organization=organization,
                    project=None,
                    category=category,
                    code=code,
                    defaults={"name": name, "is_system": True, "sort_order": sort_order},
                )
                MasterData.objects.get_or_create(
                    organization=organization,
                    project=project,
                    category=category,
                    code=code,
                    defaults={"name": default.name, "is_system": default.is_system, "sort_order": default.sort_order},
                )

    @staticmethod
    def _seed_document_categories(organization):
        for code, name in (
            ("id-proof", "ID Proof"),
            ("address-proof", "Address Proof"),
            ("financial", "Financial"),
            ("ekyc", "eKYC Documents"),
        ):
            category, _ = DocumentCategory.objects.get_or_create(
                organization=organization,
                code=code,
                defaults={"name": name, "is_active": True},
            )
            if not category.is_active:
                category.is_active = True
                category.save(update_fields=["is_active", "updated_at"])

    @staticmethod
    def _ensure_manager_site_visit_permissions(role):
        permissions = Permission.objects.filter(
            module="site_visits", action__in=["view", "add", "edit"]
        ) | Permission.objects.filter(module="telecalling", action="view")
        role.permissions.add(*permissions)

    @staticmethod
    def _seed_users(organization, project, roles):
        User = get_user_model()
        password_path = Path.home() / "crm-beta-demo-passwords.txt"
        existing_passwords = {}
        if password_path.exists():
            for line in password_path.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    role, password = line.split("=", 1)
                    existing_passwords[role.strip()] = password.strip()
        new_passwords = {}
        memberships = []
        for code, label in DEMO_ROLES:
            username = f"{code}@{organization.slug}.invalid"
            user, created = User.objects.get_or_create(username=username, defaults={"email": username, "is_active": True})
            if created:
                password = secrets.token_urlsafe(24)
                user.set_password(password)
                user.save(update_fields=["password", "is_active"])
                new_passwords[code] = password
            else:
                password = existing_passwords.get(code)
                if not password or not user.check_password(password):
                    password = secrets.token_urlsafe(24)
                    user.set_password(password)
                    user.save(update_fields=["password", "is_active"])
                    new_passwords[code] = password
            membership, _ = OrganizationMembership.objects.get_or_create(
                organization=organization,
                user=user,
                defaults={"role": code if code in {"admin", "manager", "telecaller"} else OrganizationMembership.Role.TELECALLER},
            )
            membership.organization_role = roles[code]
            membership.role = code if code in {"admin", "manager", "telecaller"} else OrganizationMembership.Role.TELECALLER
            membership.is_active = True
            membership.save(update_fields=["organization_role", "role", "is_active"])
            project.assigned_memberships.add(membership)
            ProjectAssignment.objects.update_or_create(
                membership=membership,
                project=project,
                defaults={"role": roles[code]},
            )
            memberships.append(membership)
        return memberships, new_passwords

    @staticmethod
    def _seed_plots(organization, project, created_by=None):
        blocks = []
        for index in (1, 2):
            block, _ = Block.objects.get_or_create(
                organization=organization,
                code=f"DEMO-B{index}",
                defaults={"project": project, "name": f"Demo Block {index}"},
            )
            blocks.append(block)
        for index in range(1, 21):
            block = blocks[(index - 1) // 10]
            Plot.objects.update_or_create(
                organization=organization,
                block=block,
                plot_number=f"D-{index:03d}",
                defaults={
                    "project": project,
                    "size": "1000.00",
                    "plot_type": Plot.PlotType.RESIDENTIAL,
                    "rate_per_sq_unit": "5000.00",
                    "total_price": "5000000.00",
                    "facing": "East",
                    "dimensions": "25 x 40",
                    "status": Plot.Status.AVAILABLE,
                    "description": "Demo-only beta plot.",
                    "created_by": created_by,
                },
            )

    @staticmethod
    def _seed_leads(organization, project):
        for first_name, last_name, email, phone, source in DEMO_LEADS:
            Lead.objects.update_or_create(
                organization=organization,
                project=project,
                email=email,
                defaults={"first_name": first_name, "last_name": last_name, "phone": phone, "source": source},
            )

    @staticmethod
    def _seed_parameters(organization, project):
        for definition in PARAMETER_REGISTRY.values():
            if definition.scope != "project":
                continue
            SystemParameter.objects.update_or_create(
                organization=organization,
                project=project,
                parameter_key=definition.key,
                defaults={
                    "parameter_name": definition.name,
                    "value": definition.default,
                    "data_type": definition.data_type,
                    "description": definition.description,
                    "is_active": True,
                },
            )

    @staticmethod
    def _seed_integrations(organization):
        samples = {
            IntegrationConfiguration.Type.META_ADS: {"sample_payloads": [{"id": "meta-demo-1", "name": "Demo Meta Lead"}]},
            IntegrationConfiguration.Type.GOOGLE_ADS: {"sample_payloads": [{"id": "google-demo-1", "name": "Demo Google Lead"}]},
        }
        for integration_type, sample in samples.items():
            IntegrationConfiguration.objects.update_or_create(
                organization=organization,
                integration_type=integration_type,
                name=f"Beta mock {integration_type}",
                defaults={
                    "enabled": True,
                    "status": IntegrationConfiguration.Status.CONFIGURED,
                    "configuration": {"mode": "mock", **sample},
                    "encrypted_secrets": encrypt_secret({"mode": "mock"}),
                },
            )

    @staticmethod
    def _seed_extended_fixtures(organization, project, memberships):
        """Create only demo-scoped records needed by the browser acceptance extension."""
        User = get_user_model()
        admin = User.objects.get(username=f"admin@{organization.slug}.invalid")
        manager = User.objects.get(username=f"manager@{organization.slug}.invalid")
        telecaller = User.objects.get(username=f"telecaller@{organization.slug}.invalid")
        booked_lead, _ = Lead.objects.update_or_create(
            organization=organization,
            email="booked.demo.invalid",
            defaults={
                "project": project,
                "first_name": "Booked",
                "last_name": "Demo Customer",
                "phone": "9000000099",
                "source": Lead.Source.WEBSITE,
            },
        )
        plot = Plot.objects.filter(organization=organization, project=project).order_by("id").first()
        if plot is None:
            raise CommandError("Extended beta fixtures require at least one demo plot.")
        plot.status = Plot.Status.BOOKED
        plot.save(update_fields=["status", "updated_at"])
        booking, _ = PlotBooking.objects.update_or_create(
            organization=organization,
            lead=booked_lead,
            plot=plot,
            defaults={
                "status": PlotBooking.Status.CONFIRMED,
                "final_price": Decimal("5000000.00"),
                "created_by": admin,
                "notes": "Browser acceptance booked-lead fixture.",
            },
        )
        payment, _ = Payment.objects.update_or_create(
            organization=organization,
            payment_id="BETA-BOOKED-PAYMENT",
            defaults={
                "booking": booking,
                "amount": Decimal("100000.00"),
                "payment_method": Payment.Method.UPI,
                "status": Payment.Status.SUCCESS,
                "transaction_reference": "BETA-BOOKED-REF",
                "payment_date": date.today(),
                "received_by": manager,
                "notes": "Browser acceptance confirmed payment.",
            },
        )
        PaymentReceipt.objects.update_or_create(
            payment=payment,
            defaults={"organization": organization, "receipt_number": "BETA-RECEIPT-001"},
        )
        # Step 32 starts with a confirmed payment that the Manager can request
        # a refund on; the Admin creates the approval state during the run.
        PaymentRefund.objects.filter(payment=payment).delete()

        category, _ = ExpenseCategory.objects.update_or_create(
            organization=organization,
            project=project,
            name="Browser acceptance expense",
            defaults={"description": "Demo-only extended browser fixture."},
        )
        expense_id = "BETA-EXTENDED-EXPENSE"
        existing_expense = Expense.objects.filter(expense_id=expense_id).first()
        if existing_expense and existing_expense.organization_id != organization.id:
            expense_id = f"BETA-EXTENDED-EXPENSE-{organization.id}"
        expense, _ = Expense.objects.update_or_create(
            expense_id=expense_id,
            defaults={
                "organization": organization,
                "project": project,
                "submitted_by": telecaller,
                "date": date.today(),
                "category": category,
                "amount": Decimal("1250.00"),
                "description": "Browser acceptance expense with receipt",
                "payment_method": Expense.PaymentMethod.CASH,
                "status": Expense.Status.PENDING_APPROVAL,
                "payment_status": Expense.PaymentStatus.UNPAID,
                "is_deleted": False,
            },
        )
        if not expense.receipt:
            expense.receipt.save("beta-extended-receipt.pdf", ContentFile(b"%PDF-1.4\nDemo beta receipt\n%%EOF\n"), save=True)

    @staticmethod
    def _write_password_file(path, new_passwords):
        lines = ["# Demo beta credentials. Keep this file outside the repository."]
        for code, password in sorted(new_passwords.items()):
            lines.append(f"{code}={password}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
