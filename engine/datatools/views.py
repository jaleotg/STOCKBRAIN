import io
import tempfile

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse


@staff_member_required
def db_tools(request):
    """
    Simple backend panel for full DB export/import/delete.
    Export: returns JSON dumpdata (natural keys).
    Import: flushes DB, then loads uploaded JSON.
    Delete: flushes DB.
    """
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "export":
            out = io.StringIO()
            call_command(
                "dumpdata",
                "--natural-foreign",
                "--natural-primary",
                stdout=out,
            )
            content = out.getvalue()
            response = HttpResponse(content, content_type="application/json")
            response["Content-Disposition"] = 'attachment; filename="stockbrain-full.json"'
            return response

        if action == "delete":
            call_command("flush", "--noinput")
            messages.success(request, "Database wiped (all tables cleared).")
            return redirect(reverse("db_tools"))

        if action == "import":
            uploaded = request.FILES.get("import_file")
            if not uploaded:
                messages.error(request, "No file provided for import.")
                return redirect(reverse("db_tools"))
            try:
                # Read uploaded content
                data_bytes = uploaded.read()
                # Flush everything first
                call_command("flush", "--noinput")
                # Write to temp file for loaddata
                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                    tmp.write(data_bytes)
                    tmp.flush()
                    call_command("loaddata", tmp.name)
                messages.success(request, "Import completed (database replaced with uploaded dump).")
            except Exception as exc:  # pylint: disable=broad-except
                messages.error(request, f"Import failed: {exc}")
            return redirect(reverse("db_tools"))

        messages.error(request, "Unknown action.")
        return redirect(reverse("db_tools"))

    return render(request, "datatools/db_tools.html")
