from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("worklog", "0011_merge_20251212_1520"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkLogDocument",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("docx_file", models.FileField(blank=True, help_text="Generated DOCX representation (WL-YYMMDD-Name_Surname.docx)", null=True, upload_to="worklogs/docx/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "worklog",
                    models.OneToOneField(
                        help_text="Work log this DOCX file belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="docx_document",
                        to="worklog.worklog",
                    ),
                ),
            ],
            options={
                "verbose_name": "Work Log DOCX",
                "verbose_name_plural": "Work Log DOCX files",
            },
        ),
    ]

