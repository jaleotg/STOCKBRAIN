import smtplib
from email.message import EmailMessage

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from .models import AdminEmailSettings


class AdminEmailSettingsForm(forms.ModelForm):
    PLACEHOLDER = "••••••••"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.smtp_password:
            self.fields["smtp_password"].initial = self.PLACEHOLDER
            self.fields["smtp_password"].widget.attrs["placeholder"] = self.PLACEHOLDER
        # avoid browser autofill
        self.fields["smtp_password"].widget.attrs["autocomplete"] = "new-password"

    def clean_smtp_password(self):
        value = self.cleaned_data.get("smtp_password") or ""
        if value == self.PLACEHOLDER and self.instance and self.instance.smtp_password:
            # keep existing hashed password
            return self.instance.smtp_password
        return value

    class Meta:
        model = AdminEmailSettings
        fields = "__all__"
        widgets = {
            "smtp_password": forms.PasswordInput(render_value=True),
        }
        help_texts = {
            "smtp_password": "Use an app-specific password; value is stored hashed and cannot be read back.",
        }


@admin.register(AdminEmailSettings)
class AdminEmailSettingsAdmin(admin.ModelAdmin):
    list_display = ("smtp_host", "smtp_port", "use_tls", "use_ssl", "from_email")
    readonly_fields = ("singleton",)
    form = AdminEmailSettingsForm
    change_form_template = "admin/config/adminemailsettings/change_form.html"
    fieldsets = (
        (None, {
            "fields": (
                "smtp_host",
                "smtp_port",
                "use_tls",
                "use_ssl",
                "smtp_username",
                "smtp_password",
                "from_email",
                "timeout",
            ),
            "description": (
                "<strong>Example (Gmail):</strong><br>"
                "Host: smtp.gmail.com, Port: 587 (TLS) or 465 (SSL).<br>"
                "TLS ON with 587, SSL ON with 465 (never both).<br>"
                "Login: full Gmail address. Password: App Password from Google Account (not regular password).<br>"
                "From: usually same as login."
            ),
        }),
    )

    def has_add_permission(self, request):
        # singleton – brak nowych wpisów
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = AdminEmailSettings.objects.first()
        if not obj:
            obj = AdminEmailSettings.objects.create(
                smtp_host="",
                smtp_port=587,
                use_tls=True,
                use_ssl=False,
                smtp_username="",
                smtp_password="",
                from_email="",
            )
        return self.change_view(request, object_id=str(obj.pk), extra_context=extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if request.method == "POST" and "_send_test" in request.POST:
            obj = self.get_object(request, object_id)
            form_class = self.get_form(request, obj)
            form = form_class(request.POST, request.FILES, instance=obj)
            if form.is_valid():
                cd = form.cleaned_data
                # Use the raw value from POST; the cleaned value would reuse the hashed
                # password from the instance, which cannot be used for SMTP login.
                raw_password = request.POST.get("smtp_password", "")
                if raw_password == form_class.PLACEHOLDER:
                    raw_password = ""
                if not raw_password:
                    messages.error(request, "Please enter SMTP password (use app password for Gmail).")
                else:
                    try:
                        self._send_test_email(cd, raw_password)
                        messages.success(request, "Test e-mail sent.")
                    except Exception as exc:  # pylint: disable=broad-except
                        messages.error(request, f"Test e-mail failed: {exc}")
            else:
                messages.error(request, "Please correct errors before sending test e-mail.")
            # redirect to avoid missing inline context errors and keep admin breadcrumbs
            return redirect(
                reverse(
                    f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change",
                    args=[object_id],
                )
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def _send_test_email(self, cd, raw_password):
        host = cd.get("smtp_host")
        port = cd.get("smtp_port") or 587
        use_tls = cd.get("use_tls")
        use_ssl = cd.get("use_ssl")
        username = cd.get("smtp_username")
        from_email = cd.get("from_email")
        timeout = cd.get("timeout") or 30
        to_email = from_email or username

        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        try:
            server.ehlo()
            if use_tls and not use_ssl:
                server.starttls()
            if username:
                server.login(username, raw_password)
            msg = EmailMessage()
            msg["Subject"] = "StockBrain test e-mail"
            msg["From"] = from_email or username
            msg["To"] = to_email
            msg.set_content("This is a StockBrain test e-mail.")
            server.send_message(msg)
        finally:
            server.quit()
