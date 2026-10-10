"""
Database Backup Utilities - University Council Management System
Uses the SQLite online-backup API so the copy is consistent even while
the server is running.
"""
import sqlite3
from pathlib import Path

from django.conf import settings
from django.utils import timezone

KEEP_LAST_BACKUPS = 60


def _prune_old_backups(backup_dir: Path, keep: int = KEEP_LAST_BACKUPS):
    files = sorted(backup_dir.glob('db_backup_*.sqlite3'))
    for old in files[:-keep] if len(files) > keep else []:
        try:
            old.unlink()
        except OSError:
            pass


def create_backup(user=None, reason='يدوي'):
    """Create a timestamped consistent copy of the SQLite DB and log it.

    Returns the backup Path on success, or None on failure.
    """
    from council.models import BackupLog

    real_user = user if (user is not None and getattr(user, 'is_authenticated', False)) else None
    engine = settings.DATABASES['default'].get('ENGINE', '')
    backup_dir = Path(settings.BASE_DIR) / 'backups'
    try:
        backup_dir.mkdir(exist_ok=True)
        ts = timezone.localtime().strftime('%Y%m%d_%H%M%S')
        if 'sqlite3' in engine:
            db_path = Path(settings.DATABASES['default']['NAME'])
            out = backup_dir / f'db_backup_{ts}.sqlite3'
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(str(out))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            size = out.stat().st_size
        else:
            from django.core.management import call_command
            out = backup_dir / f'db_backup_{ts}.json'
            with open(out, 'w', encoding='utf-8') as f:
                call_command('dumpdata', 'accounts', 'council', stdout=f)
            size = out.stat().st_size
        BackupLog.objects.create(
            backup_path=str(out), size_bytes=size,
            created_by=real_user, trigger_reason=reason[:200], success=True,
        )
        _prune_old_backups(backup_dir)
        return out
    except Exception as exc:  # pragma: no cover - defensive
        try:
            BackupLog.objects.create(
                backup_path='', size_bytes=0, created_by=real_user,
                trigger_reason=f'{reason} – فشل: {exc}'[:200], success=False,
            )
        except Exception:
            pass
        return None
