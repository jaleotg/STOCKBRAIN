from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AdminEmailSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton", models.PositiveSmallIntegerField(default=1, editable=False, help_text="Singleton guard", unique=True)),
                ("smtp_host", models.CharField(max_length=255)),
                ("smtp_port", models.PositiveIntegerField(default=587)),
                ("use_tls", models.BooleanField(default=True)),
                ("use_ssl", models.BooleanField(default=False)),
                ("smtp_username", models.CharField(blank=True, max_length=255)),
                ("smtp_password", models.CharField(blank=True, max_length=255)),
                ("from_email", models.EmailField(help_text="Default FROM address", max_length=254)),
                ("timeout", models.PositiveIntegerField(default=30, help_text="Seconds")),
            ],
            options={
                "verbose_name": "Admin E-mail Settings",
                "verbose_name_plural": "Admin E-mail Settings",
            },
        ),
    ]
