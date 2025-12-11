from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0007_editcondition"),
        ("worklog", "0007_worklogemailsettings"),
    ]

    operations = [
        # merge migration – no operations, just resolves graph
    ]

