from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0013_userprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="previous_login",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
