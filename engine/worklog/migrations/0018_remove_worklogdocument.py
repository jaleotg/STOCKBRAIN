from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0017_remove_worklogentry_part_add_location_fields"),
    ]

    operations = [
        migrations.DeleteModel(
            name="WorkLogDocument",
        ),
    ]
