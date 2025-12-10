from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0002_remove_vehiclelocation_location_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="StandardWorkHours",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_time", models.TimeField(help_text="Start of standard work day (24h)")),
                ("end_time", models.TimeField(help_text="End of standard work day (24h)")),
            ],
            options={
                "verbose_name": "Standard Work Hours",
                "verbose_name_plural": "Standard Work Hours",
            },
        ),
    ]
