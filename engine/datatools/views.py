import os
import tempfile
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from zoneinfo import ZoneInfo


BACKUP_DIR = Path(settings.BASE_DIR).parent / "db-backups"
KUWAIT_TZ = ZoneInfo("Asia/Kuwait")


def _pg_env():
    db = settings.DATABASES["default"]
    env = os.environ.copy()
    if db.get("USER"):
        env["PGUSER"] = str(db["USER"])
    if db.get("PASSWORD"):
        env["PGPASSWORD"] = str(db["PASSWORD"])
    if db.get("HOST"):
        env["PGHOST"] = str(db["HOST"])
    if db.get("PORT"):
        env["PGPORT"] = str(db["PORT"])
    return env


def _base_db_cmd(executable):
    db = settings.DATABASES["default"]
    cmd = [executable]
    host = db.get("HOST")
    port = db.get("PORT")
    if host:
        cmd.extend(["-h", str(host)])
    if port:
        cmd.extend(["-p", str(port)])
    if db.get("USER"):
        cmd.extend(["-U", str(db["USER"])])
    cmd.extend(["-d", str(db["NAME"])])
    return cmd


def _export_database(dest_path):
    cmd = _base_db_cmd("pg_dump")
    cmd.extend(["-F", "p", "--no-owner", "--no-privileges", "-f", dest_path])
    result = subprocess.run(cmd, capture_output=True, text=True, env=_pg_env())
    return result.returncode, result.stdout, result.stderr


def _export_database_bytes():
    cmd = _base_db_cmd("pg_dump")
    cmd.extend(["-F", "p", "--no-owner", "--no-privileges"])
    return subprocess.run(cmd, capture_output=True, text=False, env=_pg_env())


def _run_psql(sql):
    cmd = _base_db_cmd("psql")
    cmd.extend(["-v", "ON_ERROR_STOP=1", "-c", sql])
    return subprocess.run(cmd, capture_output=True, text=True, env=_pg_env())


def _drop_and_recreate_schema():
    drop = _run_psql("DROP SCHEMA public CASCADE;")
    if drop.returncode != 0:
        return drop
    create = _run_psql("CREATE SCHEMA public;")
    if create.returncode != 0:
        return create
    db_user = settings.DATABASES["default"].get("USER")
    if db_user:
        grant_user = _run_psql(f'GRANT ALL ON SCHEMA public TO "{db_user}";')
        if grant_user.returncode != 0:
            return grant_user
    return _run_psql("GRANT ALL ON SCHEMA public TO public;")


def _import_sql_file(path):
    cmd = _base_db_cmd("psql")
    cmd.extend(["-v", "ON_ERROR_STOP=1", "-f", path])
    return subprocess.run(cmd, capture_output=True, text=True, env=_pg_env())


def _default_export_path():
    timestamp = datetime.now(tz=KUWAIT_TZ).strftime("%Y%m%d-%H%M")
    filename = f"DesertBrain-DB-{timestamp}.sql"
    return str(BACKUP_DIR / filename)


@staff_member_required
def db_tools(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access required.")

    default_path = _default_export_path()
    default_filename = os.path.basename(default_path)
    section = request.GET.get("section") or "export"
    if section not in {"export", "restore", "delete"}:
        section = "export"

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "export":
            result = _export_database_bytes()
            if result.returncode == 0:
                response = HttpResponse(
                    result.stdout,
                    content_type="application/sql",
                )
                response["Content-Disposition"] = f'attachment; filename="{default_filename}"'
                return response
            error_msg = ""
            if result.stderr:
                error_msg = result.stderr.decode(errors="ignore")
            messages.error(request, f"Export failed: {error_msg}")
            return redirect(f"{reverse('db_tools')}?section=export")

        if action == "import_restore":
            upload = request.FILES.get("import_file")
            password = request.POST.get("import_password", "")
            if not upload:
                messages.error(request, "Please provide a SQL dump file to import.")
                return redirect(reverse("db_tools"))
            if not request.user.check_password(password):
                messages.error(request, "Password verification failed. Import aborted.")
                return redirect(f"{reverse('db_tools')}?section=restore")

            with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
                for chunk in upload.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            try:
                reset = _drop_and_recreate_schema()
                if reset.returncode != 0:
                    raise RuntimeError(reset.stderr or reset.stdout)
                restore = _import_sql_file(tmp_path)
                if restore.returncode != 0:
                    raise RuntimeError(restore.stderr or restore.stdout)
                messages.success(request, "Database restored from uploaded file.")
            except Exception as exc:  # pylint: disable=broad-except
                messages.error(request, f"Import failed: {exc}")
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return redirect(f"{reverse('db_tools')}?section=restore")

        if action == "delete_all":
            delete_password = request.POST.get("delete_password", "")
            confirm_backup = request.POST.get("confirm_backup") == "on"
            if not request.user.check_password(delete_password):
                messages.error(request, "Password verification failed. Deletion cancelled.")
                return redirect(f"{reverse('db_tools')}?section=delete")
            if not confirm_backup:
                messages.error(request, "You must confirm that you have a full backup.")
                return redirect(f"{reverse('db_tools')}?section=delete")

            result = _drop_and_recreate_schema()
            if result.returncode != 0:
                messages.error(request, f"Delete failed: {result.stderr or result.stdout}")
                return redirect(f"{reverse('db_tools')}?section=delete")
            warning = (
                "<h2>Database deleted</h2>"
                "<p>The entire database has been dropped. "
                "The web interface will not function until you restore a full dump.</p>"
                "<p>To restore from shell run:</p>"
                "<pre>psql -d {db} -f /path/to/backup.sql</pre>".format(
                    db=settings.DATABASES["default"]["NAME"]
                )
            )
            return HttpResponse(warning)

        messages.error(request, "Unknown action.")
        return redirect(f"{reverse('db_tools')}?section={section}")

    context = {
        "default_export_filename": default_filename,
        "backup_dir": str(BACKUP_DIR),
        "section": section,
        "show_export": section == "export",
        "show_restore": section == "restore",
        "show_delete": section == "delete",
    }
    context.update(admin.site.each_context(request))
    return render(request, "datatools/db_tools.html", context)
