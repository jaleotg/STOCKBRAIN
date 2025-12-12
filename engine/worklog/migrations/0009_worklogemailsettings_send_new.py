from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0008_merge_0007_editcondition_0007_worklogemailsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="worklogemailsettings",
            name="send_new",
            field=models.BooleanField(
                default=False,
                help_text="Send newly created work logs to the specified e-mail",
            ),
        ),
    ]

