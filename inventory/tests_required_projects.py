from django.test import SimpleTestCase

from expenses.models import Expense
from leads.models import Lead, Sitevisit

from .models import Block, Plot


class RequiredProjectFieldTests(SimpleTestCase):
    """FR-P0-01, FR-P0-02, G-1 item 5: project-scope rows require a project."""

    def test_project_scope_models_require_project_fr_p0_02_g1_item_5(self):
        for model in (Lead, Sitevisit, Block, Plot, Expense):
            with self.subTest(model=model.__name__):
                self.assertFalse(model._meta.get_field("project").null)
                self.assertFalse(model._meta.get_field("project").blank)
