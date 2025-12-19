from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .models import PoetryText, PoetryType


@login_required
def random_poetry_text(request):
    type_name = (request.GET.get("type") or "").strip()
    if not type_name:
        return JsonResponse({"ok": False, "error": "Missing type."}, status=400)

    poetry_type = PoetryType.objects.filter(name__iexact=type_name).first()
    if not poetry_type:
        return JsonResponse({"ok": False, "error": "Type not found."}, status=404)

    entry = (
        PoetryText.objects
        .filter(poetry_type=poetry_type)
        .select_related("created_by")
        .order_by("?")
        .first()
    )
    if not entry:
        return JsonResponse({"ok": False, "error": "No texts available."}, status=404)

    return JsonResponse({
        "ok": True,
        "type": poetry_type.name,
        "text": entry.text,
        "author": entry.created_by.get_username(),
    })
