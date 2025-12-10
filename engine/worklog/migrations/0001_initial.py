from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="VehicleLocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255, help_text="Vehicle name or identifier")),
                ("location", models.CharField(max_length=255, help_text="Current location / assignment")),
            ],
            options={
                "verbose_name": "Vehicle & Location",
                "verbose_name_plural": "Vehicles & Locations",
                "ordering": ["name"],
            },
        ),
    ]
