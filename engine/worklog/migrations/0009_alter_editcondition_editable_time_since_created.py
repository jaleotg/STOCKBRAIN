from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0008_merge_0007_editcondition_0007_worklogemailsettings"),
    ]

    operations = [
        migrations.AlterField(
            model_name="editcondition",
            name="editable_time_since_created",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Time window (hours) to allow editing after creation. 0 = no time limit.",
            ),
        ),
    ]
