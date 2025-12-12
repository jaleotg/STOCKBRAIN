from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password
from django.db import models


class AdminEmailSettings(models.Model):
    singleton = models.PositiveSmallIntegerField(
        default=1,
        unique=True,
        editable=False,
        help_text="Singleton guard",
    )
    smtp_host = models.CharField(
        max_length=255,
        help_text="SMTP server (e.g. Gmail: smtp.gmail.com)",
    )
    smtp_port = models.PositiveIntegerField(
        default=587,
        help_text="SMTP port (Gmail TLS: 587, Gmail SSL: 465)",
    )
    use_tls = models.BooleanField(
        default=True,
        help_text="Use TLS (Gmail: ON with port 587)",
    )
    use_ssl = models.BooleanField(
        default=False,
        help_text="Use SSL (Gmail: ON only with port 465; never with TLS together)",
    )
    smtp_username = models.CharField(
        max_length=255,
        blank=True,
        help_text="SMTP login (e.g. your full Gmail address)",
    )
    smtp_password = models.CharField(
        max_length=255,
        blank=True,
        help_text="SMTP password (Gmail: App Password from Google Account > Security > App passwords)",
    )
    from_email = models.EmailField(
        help_text="From address (usually the same as your login)",
    )
    timeout = models.PositiveIntegerField(
        default=30,
        help_text="Timeout in seconds (default 30)",
    )

    class Meta:
        verbose_name = "Admin E-mail Settings"
        verbose_name_plural = "Admin E-mail Settings"

    def clean(self):
        if self.use_tls and self.use_ssl:
            raise ValidationError("Choose either TLS or SSL, not both.")

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.smtp_host}:{self.smtp_port}"
