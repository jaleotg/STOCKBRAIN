from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0006_worklog_worklogentry"),
    ]

    operations = [
        migrations.CreateModel(
            name="EditCondition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "singleton",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        help_text="Singleton guard to keep only one record.",
                        unique=True,
                    ),
                ),
                (
                    "only_last_wl_editable",
                    models.BooleanField(
                        default=True,
                        help_text="If yes, only the author's last Work Log can be edited.",
                    ),
                ),
                (
                    "editable_time_since_created",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Time window (minutes) to allow editing after creation. 0 = no time limit.",
                    ),
                ),
            ],
            options={
                "verbose_name": "Edit Condition",
                "verbose_name_plural": "Edit Condition",
            },
        ),
    ]

