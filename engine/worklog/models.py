from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import PROTECT, CASCADE

from inventory.models import Unit


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
    sort_index = models.PositiveIntegerField(
        default=0,
        help_text="Manual order for dropdowns (lower = higher).",
    )

    class Meta:
        ordering = ["sort_index", "name"]
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
        verbose_name = "Log Edition Condition"
        verbose_name_plural = "Log Edition Conditions"

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
    email_pending = models.BooleanField(
        default=False,
        help_text="If true, an e-mail send is scheduled.",
    )
    email_scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Planned send time (Kuwait).",
    )
    email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the work log e-mail was actually sent.",
    )

    class Meta:
        ordering = ["-due_date", "-created_at"]
        verbose_name = "Work Log"
        verbose_name_plural = "Log List"

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
    inventory_rack = models.IntegerField(null=True, blank=True)
    inventory_shelf = models.CharField(max_length=4, blank=True)
    inventory_box = models.CharField(max_length=50, blank=True)
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

    @property
    def inventory_location_display(self):
        parts = []
        if self.inventory_rack is not None:
            parts.append(str(self.inventory_rack))
        if self.inventory_shelf:
            parts.append(str(self.inventory_shelf).upper())
        if self.inventory_box:
            parts.append(self.inventory_box)
        return "-".join(parts)

    def save(self, *args, **kwargs):
        if self.inventory_shelf:
            self.inventory_shelf = self.inventory_shelf.upper()
        super().save(*args, **kwargs)


class WorkLogEntryStateChange(models.Model):
    entry = models.ForeignKey(WorkLogEntry, on_delete=CASCADE, related_name="state_changes")
    old_state = models.ForeignKey(JobState, null=True, blank=True, on_delete=PROTECT, related_name="+")
    new_state = models.ForeignKey(JobState, on_delete=PROTECT, related_name="+")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=PROTECT, related_name="wl_state_changes")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]
        verbose_name = "Work Log Entry State Change"
        verbose_name_plural = "Work Log Entry State Changes"

    def __str__(self):
        return f"{self.entry} {self.old_state} -> {self.new_state}"


class WorklogEmailSettings(models.Model):
    send_new = models.BooleanField(
        default=False,
        help_text="Send newly created work logs to the specified e-mail",
    )
    send_edit = models.BooleanField(
        default=False,
        help_text="Send notification when a work log is edited",
    )
    enable_scheduled_send = models.BooleanField(
        default=True,
        help_text="If disabled, scheduled worklogs will not be auto-sent by the background task.",
    )
    recipient_email = models.EmailField(help_text="Docelowy adres e-mail do wysyłki worklogów")
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="worklog_email_rules",
        help_text="Użytkownicy, których worklogi będą oznaczone do wysyłki",
    )

    class Meta:
        verbose_name = "Log Email Rule"
        verbose_name_plural = "Log Email Rules"

    def __str__(self):
        return self.recipient_email
