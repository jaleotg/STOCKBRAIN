from django.conf import settings
from django.db import models
from django.db.models import PROTECT


class PoetryType(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Poetry type"
        verbose_name_plural = "Poetry types"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class PoetryText(models.Model):
    poetry_type = models.ForeignKey(PoetryType, on_delete=PROTECT, related_name="texts")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=PROTECT,
        related_name="poetry_texts",
    )
    text = models.TextField()

    class Meta:
        verbose_name = "Poetry text"
        verbose_name_plural = "Poetry texts"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.poetry_type} — {self.created_by}"
