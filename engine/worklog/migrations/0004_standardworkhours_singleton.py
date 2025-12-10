from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0003_standardworkhours"),
    ]

    operations = [
        migrations.AddField(
            model_name="standardworkhours",
            name="singleton",
            field=models.PositiveSmallIntegerField(
                default=1,
                editable=False,
                unique=True,
                help_text="Singleton guard to keep only one record.",
            ),
        ),
    ]
