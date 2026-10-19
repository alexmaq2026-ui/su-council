"""
Council Middleware - University Council Management System

SessionLifecycleGuardMiddleware (server-side enforcement, cannot be bypassed
by typing URLs directly):
  1. Draft visibility: sessions in the 'draft' stage are visible only to users
     granted «الاطلاع على الجلسات في مرحلة التحضير» or «نقل الجلسة بين المراحل»
     (or the super admin).
  2. Freezing: any modification of a frozen session or any of its components
     (topics, tables, attachments, recordings, votes, decisions, attendance)
     is blocked.
  3. Voting is accepted only while the session is in the 'active' stage.
  4. Daily automatic backup: the first request of each day triggers a backup.
"""
import sys

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import Resolver404, resolve
from django.utils import timezone

# url_name -> kwarg holding the SESSION pk
_SESSION_KW = {
    'session_detail': 'pk', 'session_edit': 'pk', 'session_delete': 'pk',
    'session_attendance': 'pk', 'session_export': 'pk',
    'topic_create': 'session_pk', 'topic_import': 'session_pk', 'import_word': 'session_pk',
}
# url_name -> kwarg holding the TOPIC pk
_TOPIC_KW = {
    'topic_detail': 'pk', 'topic_edit': 'pk', 'topic_delete': 'pk', 'topic_status': 'pk',
    'table_create': 'topic_pk', 'attachment_upload': 'topic_pk', 'recording_save': 'topic_pk',
    'vote': 'topic_pk', 'vote_results': 'topic_pk',
    'decision_edit': 'topic_pk', 'decision_delete': 'topic_pk',
}
_TABLE_NAMES = {'table_edit', 'table_delete'}
_ATTACHMENT_NAMES = {'attachment_delete'}
_RECORDING_NAMES = {'recording_delete'}

# Pages that only READ data – allowed on frozen sessions
_READ_ONLY = {'session_detail', 'session_export', 'topic_detail', 'vote_results'}
# Endpoints called via fetch/AJAX – answer with JSON instead of redirect
_AJAX_NAMES = {'vote', 'recording_save'}

_RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == 'test'


def _resolve_session(name, kwargs):
    from council.models import CouncilSession, Topic, TopicAttachment, TopicRecording, TopicTable
    try:
        if name in _SESSION_KW:
            return CouncilSession.objects.filter(pk=kwargs.get(_SESSION_KW[name])).first()
        if name in _TOPIC_KW:
            t = Topic.objects.select_related('session').filter(pk=kwargs.get(_TOPIC_KW[name])).first()
            return t.session if t else None
        if name in _TABLE_NAMES:
            o = TopicTable.objects.select_related('topic__session').filter(pk=kwargs.get('pk')).first()
            return o.topic.session if o else None
        if name in _ATTACHMENT_NAMES:
            o = TopicAttachment.objects.select_related('topic__session').filter(pk=kwargs.get('pk')).first()
            return o.topic.session if o else None
        if name in _RECORDING_NAMES:
            o = TopicRecording.objects.select_related('topic__session').filter(pk=kwargs.get('pk')).first()
            return o.topic.session if o else None
    except Exception:
        return None
    return None


def _wants_json(request, name):
    return (
        name in _AJAX_NAMES
        or request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
        or request.content_type == 'application/json'
    )


class SessionLifecycleGuardMiddleware:
    _last_backup_day = None

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._daily_backup()
        blocked = self._guard(request)
        if blocked is not None:
            return blocked
        return self.get_response(request)

    # ── daily automatic backup ────────────────────────────────────────────
    def _daily_backup(self):
        if _RUNNING_TESTS:
            return
        from council.models import SystemAuditControl
        if not SystemAuditControl.is_audit_and_backup_active():
            return
        today = timezone.localdate()
        if SessionLifecycleGuardMiddleware._last_backup_day == today:
            return
        SessionLifecycleGuardMiddleware._last_backup_day = today
        import threading
        def _bg_backup():
            try:
                from council.models import BackupLog
                from council.backup import create_backup
                if not BackupLog.objects.filter(created_at__date=today, success=True).exists():
                    create_backup(reason='نسخ تلقائي يومي')
            except Exception:
                pass
        threading.Thread(target=_bg_backup, daemon=True).start()

    # ── lifecycle guard ───────────────────────────────────────────────────
    def _guard(self, request):
        try:
            match = resolve(request.path_info)
        except Resolver404:
            return None
        if match.namespace != 'council' or not match.url_name:
            return None
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None

        name = match.url_name.replace('-', '_')
        session = _resolve_session(name, match.kwargs)
        if session is None:
            return None

        from council.models import user_can_view_drafts

        # 1) Draft visibility
        if session.status == 'draft' and not user_can_view_drafts(user):
            msg = 'هذه الجلسة في مرحلة التحضير ولا يمكن الاطلاع عليها حالياً.'
            if _wants_json(request, name):
                return JsonResponse({'ok': False, 'error': msg}, status=403)
            messages.error(request, msg)
            return redirect('council:session_list')

        # 2) Frozen session – read only
        if session.status == 'frozen' and name not in _READ_ONLY:
            msg = 'هذه الجلسة مغلقة ومجمّدة. لا يمكن إجراء أي تعديل عليها إلا بعد إعادة فتحها من صاحب الصلاحية.'
            if _wants_json(request, name):
                return JsonResponse({'ok': False, 'error': msg}, status=403)
            messages.error(request, msg)
            return redirect('council:session_detail', pk=session.pk)

        # 3) Voting only in the active stage
        if name == 'vote' and request.method == 'POST' and session.status != 'active':
            msg = 'التصويت متاح فقط عندما تكون الجلسة في مرحلة «المناقشة والتصويت».'
            return JsonResponse({'ok': False, 'error': msg}, status=403)

        return None
