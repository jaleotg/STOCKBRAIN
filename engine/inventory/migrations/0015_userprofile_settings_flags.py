from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0014_userprofile_previous_login"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="after_login_go_to_wl",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="prefer_dark_theme",
            field=models.BooleanField(default=True),
        ),
    ]
