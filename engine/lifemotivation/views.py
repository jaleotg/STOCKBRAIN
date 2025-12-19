from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .models import PoetryText, PoetryType


@login_required
def random_poetry_text(request):
    type_name = (request.GET.get("type") or "").strip()
    if not type_name:
        return JsonResponse({"ok": False, "error": "Missing type."}, status=400)

    type_key = type_name.lower()
    candidates = [type_name]
    if type_key == "personal time":
        candidates.append("Personal time")
    elif type_key == "rest time":
        candidates.append("Personal Time")

    entry = None
    poetry_type = None
    for candidate in candidates:
        poetry_type = PoetryType.objects.filter(name__iexact=candidate).first()
        if not poetry_type:
            continue
        entry = (
            PoetryText.objects
            .filter(poetry_type=poetry_type)
            .select_related("created_by")
            .order_by("?")
            .first()
        )
        if entry:
            break

    if not poetry_type:
        return JsonResponse({"ok": False, "error": "Type not found."}, status=404)
    if not entry:
        return JsonResponse({"ok": False, "error": "No texts available."}, status=404)

    return JsonResponse({
        "ok": True,
        "type": poetry_type.name,
        "text": entry.text,
        "author": entry.created_by.get_username(),
    })
