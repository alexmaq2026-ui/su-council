"""
Management command: backup_db
Creates a consistent timestamped SQLite backup and logs it in BackupLog.

Usage:
    python manage.py backup_db
    python manage.py backup_db --reason "يدوي"
"""
from django.core.management.base import BaseCommand

from council.backup import create_backup


class Command(BaseCommand):
    help = 'إنشاء نسخة احتياطية من قاعدة البيانات'

    def add_arguments(self, parser):
        parser.add_argument('--reason', default='يدوي من سطر الأوامر', help='سبب النسخ الاحتياطي')

    def handle(self, *args, **options):
        out = create_backup(reason=options['reason'])
        if out:
            self.stdout.write(self.style.SUCCESS(f'تم إنشاء النسخة الاحتياطية: {out} ({out.stat().st_size:,} bytes)'))
        else:
            self.stdout.write(self.style.ERROR('فشل النسخ الاحتياطي – راجع سجل النسخ الاحتياطية.'))
