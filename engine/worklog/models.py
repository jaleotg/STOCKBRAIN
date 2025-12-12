from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import PROTECT, CASCADE

from inventory.models import InventoryItem, Unit


class VehicleLocation(models.Model):
    TYPE_CAMELEON = "cameleon"
    TYPE_CONDOR = "condor"
    TYPE_OUTDOOR = "outdoor"
    TYPE_OFFICE = "office"

    TYPE_CHOICES = [
        (TYPE_CAMELEON, "Cameleon"),
        (TYPE_CONDOR, "Condor"),
        (TYPE_OUTDOOR, "Outdoor"),
        (TYPE_OFFICE, "Office"),
    ]

    location_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_CAMELEON,
        help_text="Typ lokalizacji",
    )
    name = models.CharField(max_length=255, help_text="Nazwa lokalizacji / pojazdu")
    short_number = models.CharField(
        max_length=64,
        blank=True,
        help_text="Numer skrócony (dla Cameleon/Condor)",
    )
    full_number = models.CharField(
        max_length=128,
        blank=True,
        help_text="Numer pełny (dla Cameleon/Condor)",
    )
    description = models.TextField(
        blank=True,
        help_text="Opis (dla Outdoor/Office)",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Vehicle & Location"
        verbose_name_plural = "Vehicles & Locations"

    def __str__(self):
        if self.location_type in [self.TYPE_CAMELEON, self.TYPE_CONDOR]:
            label_num = self.short_number or self.full_number
            if label_num:
                return f"{self.name} ({label_num})"
            return self.name
        return f"{self.name} – {self.description}".strip(" –")


class StandardWorkHours(models.Model):
    singleton = models.PositiveSmallIntegerField(
        default=1,
        unique=True,
        editable=False,
        help_text="Singleton guard to keep only one record.",
    )
    start_time = models.TimeField(help_text="Start of standard work day (24h)")
    end_time = models.TimeField(help_text="End of standard work day (24h)")

    class Meta:
        verbose_name = "Standard Work Hours"
        verbose_name_plural = "Standard Work Hours"

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError("End time must be after start time.")

    def __str__(self):
        return f"{self.start_time} - {self.end_time}"

    def save(self, *args, **kwargs):
        # enforce singleton row
        self.singleton = 1
        super().save(*args, **kwargs)


class EditCondition(models.Model):
    singleton = models.PositiveSmallIntegerField(
        default=1,
        unique=True,
        editable=False,
        help_text="Singleton guard to keep only one record.",
    )
    only_last_wl_editable = models.BooleanField(
        default=True,
        help_text="If yes, only the author's last Work Log can be edited.",
    )
    editable_time_since_created = models.PositiveIntegerField(
        default=0,
        help_text="Time window (hours) to allow editing after creation. 0 = no time limit.",
    )

    class Meta:
        verbose_name = "Edit Condition"
        verbose_name_plural = "Edit Condition"

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return "Edit Condition"


class JobState(models.Model):
    short_name = models.CharField(max_length=64, unique=True, help_text="Short code")
    full_name = models.CharField(max_length=255, help_text="Full name")
    description = models.TextField(blank=True, help_text="Description")

    class Meta:
        ordering = ["short_name"]
        verbose_name = "Job State"
        verbose_name_plural = "Job States"

    def __str__(self):
        return f"{self.short_name} – {self.full_name}"


def get_default_work_hours():
    """Returns tuple (start, end) from StandardWorkHours singleton, else (None, None)."""
    try:
        cfg = StandardWorkHours.objects.first()
        if cfg:
            return cfg.start_time, cfg.end_time
    except Exception:
        pass
    return None, None


def format_author_segment(user):
    if not user:
        return "UNKNOWN"
    parts = []
    if user.first_name:
        parts.append(user.first_name.strip().title().replace(" ", ""))
    if user.last_name:
        parts.append(user.last_name.strip().title().replace(" ", ""))
    if not parts:
        parts.append(str(user.username).replace(" ", "_"))
    return "-".join(parts)


class WorkLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    due_date = models.DateField(help_text="Due date (YYYY-MM-DD)")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=PROTECT, related_name="worklogs")
    wl_number = models.CharField(max_length=128, unique=True, editable=False)
    start_time = models.TimeField(blank=True, null=True, help_text="Start time")
    end_time = models.TimeField(blank=True, null=True, help_text="End time")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-due_date", "-created_at"]
        verbose_name = "Work Log"
        verbose_name_plural = "Work Logs"

    def clean(self):
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise ValidationError("End time must be after start time.")

    def save(self, *args, **kwargs):
        # defaults for start/end time
        if self.start_time is None or self.end_time is None:
            start_default, end_default = get_default_work_hours()
            if self.start_time is None:
                self.start_time = start_default
            if self.end_time is None:
                self.end_time = end_default

        # Generate wl_number only when missing (do not change on edit)
        if not self.wl_number and self.due_date and self.author:
            due_str = self.due_date.strftime("%y%m%d")
            author_segment = format_author_segment(self.author)
            self.wl_number = f"WL-{due_str}-{author_segment}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.wl_number


class WorkLogEntry(models.Model):
    worklog = models.ForeignKey(WorkLog, on_delete=CASCADE, related_name="entries")
    vehicle_location = models.ForeignKey(VehicleLocation, on_delete=PROTECT, related_name="worklog_entries")
    job_description = models.TextField()
    state = models.ForeignKey(JobState, on_delete=PROTECT, related_name="worklog_entries")
    part = models.ForeignKey(InventoryItem, null=True, blank=True, on_delete=PROTECT, related_name="used_in_worklog_entries")
    part_description = models.TextField(blank=True)
    unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    time_hours = models.DecimalField(max_digits=5, decimal_places=2, help_text="Duration in hours (0.25 increments)")
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Work Log Entry"
        verbose_name_plural = "Work Log Entries"

    def __str__(self):
        return f"{self.worklog} - {self.vehicle_location}"


class WorklogEmailSettings(models.Model):
    send_new = models.BooleanField(
        default=False,
        help_text="Send newly created work logs to the specified e-mail",
    )
    send_edit = models.BooleanField(
        default=False,
        help_text="Send notification when a work log is edited",
    )
    recipient_email = models.EmailField(help_text="Docelowy adres e-mail do wysyłki worklogów")
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="worklog_email_rules",
        help_text="Użytkownicy, których worklogi będą oznaczone do wysyłki",
    )

    class Meta:
        verbose_name = "Worklog E-mail Rule"
        verbose_name_plural = "Worklog E-mail Rules"

    def __str__(self):
        return self.recipient_email


class WorkLogDocument(models.Model):
    worklog = models.OneToOneField(
        WorkLog,
        related_name="docx_document",
        on_delete=models.CASCADE,
        help_text="Work log this DOCX file belongs to",
    )
    docx_file = models.FileField(
        upload_to="worklogs/docx/",
        blank=True,
        null=True,
        help_text="Generated DOCX representation (WL-YYMMDD-Name_Surname.docx)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Work Log DOCX"
        verbose_name_plural = "Work Log DOCX files"

    def __str__(self):
        return f"{self.worklog} docx"
