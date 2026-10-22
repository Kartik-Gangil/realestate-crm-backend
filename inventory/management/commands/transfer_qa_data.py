from collections import OrderedDict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventory.models import (
    Block,
    Plot,
    PlotBooking,
    PlotHold,
    PlotSelection,
    PlotStatusHistory,
    Project,
    RecentlyViewedPlot,
)
from leads.models import FollowUpCall, Lead, Sitevisit
from organizations.models import Organization, OrganizationMembership, OrganizationRole


SOURCE_SLUG = "qa-demo-org"
SOURCE_PROJECT_CODE = "QA-DEMO"
TARGET_SLUG = "shrijienclave"
TARGET_PROJECT_CODE = "test"
QA_EMAIL_SUFFIX = "@qa-demo.invalid"
QA_PLOT_PREFIX = "QA-"


class Command(BaseCommand):
    help = "Move the complete deterministic QA dataset into the existing test project."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Validate and report without changing data.")

    def handle(self, *args, **options):
        with transaction.atomic():
            plan = self._build_plan()
            self._validate(plan)
            if options["dry_run"]:
                self.stdout.write(self.style.WARNING("DRY RUN: no database changes made."))
                self._write_report(plan)
                return
            counts = self._apply(plan)
            self._write_report(counts)

    def _build_plan(self):
        source = Organization.objects.filter(slug=SOURCE_SLUG).first()
        target = Organization.objects.filter(slug=TARGET_SLUG).first()
        if source is None:
            raise CommandError(f"Source organization '{SOURCE_SLUG}' does not exist.")
        if target is None:
            raise CommandError(f"Target organization '{TARGET_SLUG}' does not exist.")
        source_project = Project.objects.filter(organization=source, code=SOURCE_PROJECT_CODE).first()
        target_project = Project.objects.filter(organization=target, code=TARGET_PROJECT_CODE).first()
        if source_project is None:
            raise CommandError(f"Source project '{SOURCE_PROJECT_CODE}' does not exist.")
        if target_project is None:
            raise CommandError(f"Target project '{TARGET_PROJECT_CODE}' does not exist.")

        blocks = list(Block.objects.filter(organization=source, project=source_project))
        leads = list(Lead.objects.filter(organization=source, email__endswith=QA_EMAIL_SUFFIX))
        plots = list(Plot.objects.filter(organization=source, project=source_project, plot_number__startswith=QA_PLOT_PREFIX))
        lead_ids = {item.id for item in leads}
        plot_ids = {item.id for item in plots}
        bookings = list(PlotBooking.objects.filter(organization=source, lead_id__in=lead_ids, plot_id__in=plot_ids))
        site_visits = list(Sitevisit.objects.filter(organization=source, lead_id__in=lead_ids))
        follow_up_calls = list(FollowUpCall.objects.filter(organization=source, lead_id__in=lead_ids))
        selections = list(PlotSelection.objects.filter(organization=source, plot_id__in=plot_ids))
        holds = list(PlotHold.objects.filter(plot_id__in=plot_ids))
        history = list(PlotStatusHistory.objects.filter(plot_id__in=plot_ids))
        recently_viewed = list(RecentlyViewedPlot.objects.filter(organization=source, plot_id__in=plot_ids))

        return OrderedDict(
            source=source,
            target=target,
            source_project=source_project,
            target_project=target_project,
            blocks=blocks,
            leads=leads,
            plots=plots,
            bookings=bookings,
            site_visits=site_visits,
            follow_up_calls=follow_up_calls,
            selections=selections,
            holds=holds,
            history=history,
            recently_viewed=recently_viewed,
        )

    def _validate(self, plan):
        source = plan["source"]
        target_project = plan["target_project"]
        if Project.objects.filter(organization=source).exclude(pk=plan["source_project"].pk).exists():
            raise CommandError("Source organization contains an unrelated project; refusing destructive transfer.")
        if Block.objects.filter(organization=source).exclude(pk__in=[item.pk for item in plan["blocks"]]).exists():
            raise CommandError("Source organization contains an unrelated block; refusing destructive transfer.")
        if Lead.objects.filter(organization=source).exclude(pk__in=[item.pk for item in plan["leads"]]).exists():
            raise CommandError("Source organization contains an unrelated lead; refusing destructive transfer.")
        if Plot.objects.filter(organization=source).exclude(pk__in=[item.pk for item in plan["plots"]]).exists():
            raise CommandError("Source organization contains an unrelated plot; refusing destructive transfer.")
        block_codes = {item.code for item in plan["blocks"]}
        if Block.objects.filter(organization=target_project.organization, project=target_project, code__in=block_codes).exists():
            raise CommandError("Target project already contains a QA block with the same code.")
        plot_numbers = {item.plot_number for item in plan["plots"]}
        if Plot.objects.filter(organization=target_project.organization, project=target_project, plot_number__in=plot_numbers).exists():
            raise CommandError("Target project already contains a QA plot with the same number.")
        for membership in OrganizationMembership.objects.filter(organization=source):
            if not OrganizationMembership.objects.filter(organization=target_project.organization, user=membership.user).exists():
                if Lead.objects.filter(pk__in=[item.pk for item in plan["leads"]], assigned_membership=membership).exists():
                    raise CommandError(f"No target membership exists for assigned user {membership.user_id}.")

    def _apply(self, plan):
        source = plan["source"]
        target = plan["target"]
        target_project = plan["target_project"]
        block_map = {}
        for block in plan["blocks"]:
            block.organization = target
            block.project = target_project
            block.save(update_fields=["organization", "project", "updated_at"])
            block_map[block.pk] = block
        for plot in plan["plots"]:
            plot.organization = target
            plot.project = target_project
            plot.block = block_map[plot.block_id]
            plot.save(update_fields=["organization", "project", "block", "updated_at"])
        for lead in plan["leads"]:
            lead.organization = target
            lead.project = target_project
            if lead.assigned_membership_id:
                source_membership = OrganizationMembership.objects.get(pk=lead.assigned_membership_id)
                lead.assigned_membership = OrganizationMembership.objects.filter(organization=target, user=source_membership.user).first()
            lead.save(update_fields=["organization", "project", "assigned_membership", "updated_at"])
        for item in plan["site_visits"]:
            item.organization = target
            if item.executive_membership_id:
                source_membership = OrganizationMembership.objects.get(pk=item.executive_membership_id)
                item.executive_membership = OrganizationMembership.objects.filter(organization=target, user=source_membership.user).first()
            item.save(update_fields=["organization", "executive_membership", "updated_at"])
        for item in plan["follow_up_calls"]:
            item.organization = target
            if item.telecaller_membership_id:
                source_membership = OrganizationMembership.objects.get(pk=item.telecaller_membership_id)
                item.telecaller_membership = OrganizationMembership.objects.filter(organization=target, user=source_membership.user).first()
            item.save(update_fields=["organization"])
        for item in plan["bookings"]:
            item.organization = target
            item.save(update_fields=["organization", "updated_at"])
        for item in plan["selections"]:
            item.organization = target
            item.save(update_fields=["organization", "updated_at"])
        for item in plan["recently_viewed"]:
            item.organization = target
            item.save(update_fields=["organization"])
        # The source organization may have default roles protected by its
        # memberships. Remove only source-scoped access records after all
        # domain records have been re-parented, then remove the empty source.
        OrganizationMembership.objects.filter(organization=source).delete()
        OrganizationRole.objects.filter(organization=source).delete()
        source.delete()
        return plan

    def _write_report(self, plan):
        self.stdout.write(self.style.SUCCESS(
            "QA transfer complete: "
            f"leads={len(plan['leads'])}, blocks={len(plan['blocks'])}, plots={len(plan['plots'])}, "
            f"site_visits={len(plan['site_visits'])}, follow_up_calls={len(plan['follow_up_calls'])}, "
            f"bookings={len(plan['bookings'])}, selections={len(plan['selections'])}, "
            f"holds={len(plan['holds'])}, history={len(plan['history'])}, "
            f"recently_viewed={len(plan['recently_viewed'])}, target={TARGET_SLUG}/{TARGET_PROJECT_CODE}."
        ))
