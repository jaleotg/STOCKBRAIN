from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0018_remove_worklogdocument"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclelocation",
            name="sort_index",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Manual order for dropdowns (lower = higher).",
            ),
        ),
        migrations.AlterModelOptions(
            name="vehiclelocation",
            options={
                "ordering": ["sort_index", "name"],
                "verbose_name": "Vehicle & Location",
                "verbose_name_plural": "Vehicles & Locations",
            },
        ),
    ]
