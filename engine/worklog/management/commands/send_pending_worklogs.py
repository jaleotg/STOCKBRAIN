from django.core.management.base import BaseCommand
from django.utils import timezone

from worklog.email_utils import send_worklog_docx_email
from worklog.models import WorkLog, WorklogEmailSettings


class Command(BaseCommand):
    help = "Send scheduled/pending work log e-mails (cron-friendly)."

    def handle(self, *args, **options):
        rule = WorklogEmailSettings.objects.first()
        if not rule or not rule.enable_scheduled_send:
            self.stdout.write("Scheduled sending disabled or no rules configured; nothing to do.")
            return

        now = timezone.now()
        qs = WorkLog.objects.filter(
            email_pending=True,
            email_scheduled_at__isnull=False,
            email_scheduled_at__lte=now,
            email_sent_at__isnull=True,
        )
        sent = 0
        failed = 0
        for wl in qs:
            try:
                recipient = send_worklog_docx_email(wl, is_new=False)
                if recipient:
                    wl.email_pending = False
                    wl.email_scheduled_at = None
                    wl.email_sent_at = timezone.now()
                    wl.save(update_fields=["email_pending", "email_scheduled_at", "email_sent_at"])
                    sent += 1
                else:
                    failed += 1
            except Exception as exc:  # pragma: no cover - best-effort logging
                failed += 1
                self.stderr.write(f"Failed to send worklog {wl.id}: {exc}")

        self.stdout.write(f"Pending worklogs processed: sent={sent}, failed={failed}")
