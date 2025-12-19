import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Instrukcja crona (przykład, wstaw w `crontab -e`):
# 30 2 * * * /home/leo/STOCKBRAIN/venv/bin/python /home/leo/STOCKBRAIN/engine/manage.py cron_db_backup >> /home/leo/STOCKBRAIN/db-backups/cron-backup.log 2>&1
# (powiedz serwerowi w jaki czas: powyżej 02:30 czasu lokalnego)

KUWAIT_TZ = ZoneInfo("Asia/Kuwait")
BACKUP_DIR = Path(settings.BASE_DIR).parent / "db-backups"


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


class Command(BaseCommand):
    help = "Creates a timestamped cron backup of the entire PostgreSQL database."

    def handle(self, *args, **options):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=KUWAIT_TZ).strftime("%Y%m%d-%H%M")
        dest_path = BACKUP_DIR / f"cron-db-backup-{timestamp}.sql"

        cmd = _base_db_cmd("pg_dump")
        cmd.extend(["-F", "p", "--no-owner", "--no-privileges", "-f", str(dest_path)])
        result = subprocess.run(cmd, capture_output=True, text=True, env=_pg_env())
        if result.returncode != 0:
            dest_path.unlink(missing_ok=True)
            error = result.stderr or result.stdout or "Unknown pg_dump error."
            raise CommandError(f"pg_dump failed: {error}")

        self.stdout.write(self.style.SUCCESS(f"Database backup saved to {dest_path}"))
