from django.db import models


class DataJob(models.Model):
    DIRECTION_IMPORT = "import"
    DIRECTION_EXPORT = "export"
    DIRECTION_CHOICES = [
        (DIRECTION_IMPORT, "Import"),
        (DIRECTION_EXPORT, "Export"),
    ]

    MODE_MANUAL = "manual"
    MODE_AUTO = "auto"
    MODE_CHOICES = [
        (MODE_MANUAL, "Manual"),
        (MODE_AUTO, "Automatic"),
    ]

    SOURCE_FILE = "file"
    SOURCE_URL = "url"
    SOURCE_DB = "db"
    SOURCE_CHOICES = [
        (SOURCE_FILE, "File (CSV/XLSX)"),
        (SOURCE_URL, "URL"),
        (SOURCE_DB, "Database"),
    ]

    name = models.CharField(max_length=255, unique=True)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, default=DIRECTION_IMPORT)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_MANUAL)
    source_type = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_FILE)
    source_location = models.CharField(max_length=512, blank=True, help_text="Path/URL/DSN depending on source type.")
    schedule = models.CharField(max_length=128, blank=True, help_text="Cron-like string for automatic mode.")
    enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=64, blank=True, help_text="Last run status/info.")
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Data Job"
        verbose_name_plural = "Data Jobs"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_direction_display()} / {self.get_mode_display()})"


class DatabaseExportEntry(models.Model):
    class Meta:
        managed = False
        verbose_name = "Data Base Export"
        verbose_name_plural = "Data Base Export"

    def __str__(self):
        return "Data Base Export"


class DatabaseRestoreEntry(models.Model):
    class Meta:
        managed = False
        verbose_name = "Database Tools / Restore from File (Import)"
        verbose_name_plural = "Database Tools / Restore from File (Import)"

    def __str__(self):
        return "Database Tools / Restore from File (Import)"


class DatabaseDeleteEntry(models.Model):
    class Meta:
        managed = False
        verbose_name = "Delete All Data Base"
        verbose_name_plural = "Delete All Data Base"

    def __str__(self):
        return "Delete All Data Base"
