from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0009_worklogemailsettings_send_new"),
    ]

    operations = [
        migrations.AddField(
            model_name="worklogemailsettings",
            name="send_edit",
            field=models.BooleanField(
                default=False,
                help_text="Send notification when a work log is edited",
            ),
        ),
    ]

