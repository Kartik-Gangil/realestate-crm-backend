from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Block, Plot, Project
from leads.models import Lead
from organizations.models import Organization


QA_ORGANIZATION_SLUG = "qa-demo-org"
QA_PROJECT_CODE = "QA-DEMO"

LEAD_PAYLOADS = (
    {
        "first_name": "Asha",
        "last_name": "Mehta",
        "email": "asha.mehta@qa-demo.invalid",
        "phone": "9000000001",
        "source": Lead.Source.WEBSITE,
        "occupation": "Architect",
    },
    {
        "first_name": "Rohan",
        "last_name": "Shah",
        "email": "rohan.shah@qa-demo.invalid",
        "phone": "9000000002",
        "source": Lead.Source.FACEBOOK,
        "occupation": "Business owner",
    },
    {
        "first_name": "Neha",
        "last_name": "Patel",
        "email": "neha.patel@qa-demo.invalid",
        "phone": "9000000003",
        "source": Lead.Source.WALKIN,
        "occupation": "Teacher",
    },
)

PLOT_PAYLOADS = (
    {"plot_number": "QA-A-001", "status": Plot.Status.AVAILABLE, "total_price": "4500000.00"},
    {"plot_number": "QA-A-002", "status": Plot.Status.AVAILABLE, "total_price": "4750000.00"},
    {"plot_number": "QA-A-003", "status": Plot.Status.HOLD, "total_price": "5000000.00"},
    {"plot_number": "QA-A-004", "status": Plot.Status.BOOKED, "total_price": "5250000.00"},
    {"plot_number": "QA-A-005", "status": Plot.Status.AVAILABLE, "total_price": "5500000.00"},
    {"plot_number": "QA-A-006", "status": Plot.Status.AVAILABLE, "total_price": "5750000.00"},
)


class Command(BaseCommand):
    help = "Create or reuse non-destructive QA leads and plots for flow simulation."

    @transaction.atomic
    def handle(self, *args, **options):
        organization, organization_created = Organization.objects.get_or_create(
            slug=QA_ORGANIZATION_SLUG,
            defaults={"name": "QA Demo Organization", "is_active": True},
        )
        project, project_created = Project.objects.get_or_create(
            organization=organization,
            code=QA_PROJECT_CODE,
            defaults={"name": "QA Demo Project", "description": "Non-production data for end-to-end QA."},
        )
        block, block_created = Block.objects.get_or_create(
            organization=organization,
            code="QA-A",
            defaults={"project": project, "name": "QA Block A"},
        )

        lead_created = 0
        lead_reused = 0
        for payload in LEAD_PAYLOADS:
            _, created = Lead.objects.update_or_create(
                organization=organization,
                email=payload["email"],
                defaults={**payload, "project": project},
            )
            lead_created += int(created)
            lead_reused += int(not created)

        plot_created = 0
        plot_reused = 0
        for payload in PLOT_PAYLOADS:
            plot_defaults = {
                "project": project,
                "block": block,
                "size": "1000.00",
                "plot_type": Plot.PlotType.RESIDENTIAL,
                "rate_per_sq_unit": "5000.00",
                "total_price": payload["total_price"],
                "facing": "East",
                "dimensions": "30 x 40",
                "status": payload["status"],
                "description": "QA demo plot for end-to-end flow testing.",
            }
            _, created = Plot.objects.update_or_create(
                organization=organization,
                block=block,
                plot_number=payload["plot_number"],
                defaults=plot_defaults,
            )
            plot_created += int(created)
            plot_reused += int(not created)

        self.stdout.write(self.style.SUCCESS(
            "QA seed ready: "
            f"organization={'created' if organization_created else 'reused'}, "
            f"project={'created' if project_created else 'reused'}, "
            f"block={'created' if block_created else 'reused'}, "
            f"leads created={lead_created} reused={lead_reused}, "
            f"plots created={plot_created} reused={plot_reused}."
        ))
