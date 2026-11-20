import time
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand

from core.tasks_backend import get_database_backend


class Command(BaseCommand):
    help = "Run the database-backed Django Tasks worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=None,
            help="Seconds to wait between polls in loop mode.",
        )

    def handle(self, *args, **options):
        backend = get_database_backend()
        worker_id = uuid.uuid4().hex
        database = settings.DATABASES["default"]
        database_label = str(database.get("NAME", ""))
        if database.get("HOST"):
            database_label = f"{database['HOST']}/{database_label}"
        self.stdout.write(
            f"Worker started: database {database_label}, environment {settings.ENVIRONMENT_NAME}"
        )
        poll_interval = (
            options["poll_interval"]
            if options["poll_interval"] is not None
            else settings.TASK_WORKER_POLL_INTERVAL
        )
        if options["once"]:
            backend.run_once(worker_id)
            return
        while True:
            if not backend.run_once(worker_id):
                time.sleep(poll_interval)
