from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0016_worklogemailsettings_enable_scheduled_send"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="worklogentry",
            name="part",
        ),
        migrations.AddField(
            model_name="worklogentry",
            name="inventory_rack",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="worklogentry",
            name="inventory_shelf",
            field=models.CharField(blank=True, max_length=4),
        ),
        migrations.AddField(
            model_name="worklogentry",
            name="inventory_box",
            field=models.CharField(blank=True, max_length=50),
        ),
    ]
