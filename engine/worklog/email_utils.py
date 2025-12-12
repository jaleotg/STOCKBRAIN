import logging

from django.core.mail import EmailMessage, get_connection

from config.models import AdminEmailSettings
from .models import WorklogEmailSettings
from .docx_utils import generate_and_store_docx, render_worklog_docx

logger = logging.getLogger(__name__)


def _build_connection():
    cfg = AdminEmailSettings.objects.first()
    if not cfg:
        return None

    try:
        return get_connection(
            "django.core.mail.backends.smtp.EmailBackend",
            host=cfg.smtp_host or None,
            port=cfg.smtp_port or None,
            username=cfg.smtp_username or None,
            password=cfg.smtp_password or None,
            use_tls=cfg.use_tls,
            use_ssl=cfg.use_ssl,
            timeout=cfg.timeout or None,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to build SMTP connection: %s", exc)
        return None


def send_worklog_docx_email(worklog, is_new=True):
    """
    Send the DOCX representation of a work log to the configured recipient,
    provided the author is in the chosen users list and the corresponding
    send_new / send_edit flag is enabled.
    """
    rules = WorklogEmailSettings.objects.first()
    if not rules:
        return

    if is_new and not rules.send_new:
        return
    if (not is_new) and not rules.send_edit:
        return

    if worklog.author not in rules.users.all():
        return

    recipient = (rules.recipient_email or "").strip()
    if not recipient:
        return

    # Generate fresh bytes (do not rely on stored file)
    content = render_worklog_docx(worklog)
    if not content:
        logger.error("No DOCX content rendered for worklog %s", worklog.id)
        return
    source = "rendered-only"
    filename = f"{worklog.wl_number}.docx"
    subject = f"Desert Work Log {worklog.wl_number}"

    connection = _build_connection()
    if not connection:
        logger.error("Cannot send worklog e-mail: SMTP connection not available")
        return

    cfg = AdminEmailSettings.objects.first()
    from_email = cfg.from_email if cfg and cfg.from_email else None

    email = EmailMessage(
        subject=subject,
        body="",
        from_email=from_email,
        to=[recipient],
        connection=connection,
    )
    email.attach(
        filename,
        content,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    try:
        email.send(fail_silently=False)
        return recipient
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to send worklog e-mail: %s", exc)
        return None
