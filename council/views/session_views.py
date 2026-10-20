"""
Session Views
University Council Management System

Handles: session list, detail, create, edit, delete, attendance management,
session lifecycle (5 stages), freezing / reopening, new-session approval
requests (previous session not yet frozen), audit log and manual backup.
All views require login. Permission checks use user.can_* properties.
Server-side lifecycle enforcement also lives in council.middleware.
"""
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.conf import settings
from django.utils import timezone

from council.models import (
    CouncilSession, Attendance, Topic, TOPIC_CATEGORIES,
    SESSION_STATUS, SessionStageLog, NewSessionRequest, AuditLog, BackupLog,
    SessionRecording, user_can_view_drafts, CATEGORY_THEMES, DEFAULT_CUSTOM_THEME,
)
from council.forms import SessionForm, AttendanceFormSet
from council.forms.session_forms import AttendanceForm
from council.audit import log_action
from council.backup import create_backup


STAGE_LABELS = dict(SESSION_STATUS)


# ── Helper decorators ──────────────────────────────────────────────────────────

def permission_required_custom(perm_attr):
    """
    Decorator factory that checks a boolean property on request.user.
    perm_attr: string like 'can_add', 'can_edit', etc.
    """
    def decorator(view_func):
        @login_required(login_url='/login/')
        def wrapper(request, *args, **kwargs):
            if not getattr(request.user, perm_attr, False):
                messages.error(request, 'ليس لديك صلاحية للقيام بهذا الإجراء.')
                return redirect('council:session_list')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def _can_approve_new_session(user):
    return user.is_super or user.can_approve_new_session


def _new_session_gate(user):
    """
    م2 – Previous-session control.
    Returns (blocked, last_session, approved_request).
    blocked=True when the latest session is not frozen and the user is not an approver.
    """
    last_session = CouncilSession.objects.order_by('-date', '-session_number').first()
    if not last_session or last_session.status == 'frozen' or _can_approve_new_session(user):
        return False, last_session, None
    approved = (
        NewSessionRequest.objects
        .filter(requested_by=user, status='approved', used=False)
        .order_by('-reviewed_at')
        .first()
    )
    return True, last_session, approved


# ── Session List ───────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def session_list_view(request):
    """
    Paginated list of council sessions, sorted by date descending.
    Requires can_view_sessions. Draft sessions are hidden from users without draft visibility.
    """
    if not (request.user.is_super or request.user.can_view_sessions):
        messages.error(request, 'ليس لديك صلاحية لعرض الجلسات.')
        return redirect('/dashboard/')

    qs = CouncilSession.objects.select_related('created_by').prefetch_related('topics').order_by('-date', '-session_number')
    if not user_can_view_drafts(request.user):
        qs = qs.exclude(status='draft')

    has_past_perm = bool(request.user.is_super or getattr(request.user, 'can_view_past_sessions', False))
    if not has_past_perm:
        latest_session = qs.first()
        if latest_session:
            qs = qs.filter(pk=latest_session.pk)
        else:
            qs = qs.none()

    # Optional status filter
    status_filter = request.GET.get('status', '')
    if status_filter in STAGE_LABELS:
        qs = qs.filter(status=status_filter)

    # Optional year filter
    year_filter = request.GET.get('year', '')
    if year_filter:
        qs = qs.filter(academic_year=year_filter)

    paginator = Paginator(qs, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Distinct academic years for filter dropdown
    if not has_past_perm:
        all_years = qs.exclude(academic_year='').values_list('academic_year', flat=True).distinct()
    else:
        all_years = (
            CouncilSession.objects
            .exclude(academic_year='')
            .values_list('academic_year', flat=True)
            .distinct()
            .order_by('-academic_year')
        )

    can_approve = _can_approve_new_session(request.user)
    pending_requests = (
        NewSessionRequest.objects.select_related('requested_by', 'previous_session')
        .filter(status='pending') if can_approve else NewSessionRequest.objects.none()
    )
    my_requests = (
        NewSessionRequest.objects.select_related('reviewed_by')
        .filter(requested_by=request.user)
        .exclude(status='approved', used=True)
        .order_by('-created_at')[:3]
    )

    context = {
        'page_obj':         page_obj,
        'status_filter':    status_filter,
        'year_filter':      year_filter,
        'all_years':        all_years,
        'status_choices':   SESSION_STATUS,
        'can_approve':      can_approve,
        'pending_requests': pending_requests,
        'my_requests':      my_requests,
        'page_title':       'الجلسات',
    }
    return render(request, 'council/session_list.html', context)


# ── Session Detail ─────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def session_detail_view(request, pk):
    """
    Full session details: topics grouped by category, attendance, export button,
    lifecycle stage bar with stage controls. Requires can_view_sessions.
    """
    if not (request.user.is_super or request.user.can_view_sessions):
        messages.error(request, 'ليس لديك صلاحية لعرض تفاصيل الجلسة.')
        return redirect('/dashboard/')

    session = get_object_or_404(
        CouncilSession.objects.select_related('created_by', 'frozen_by', 'stage_changed_by'),
        pk=pk
    )
    if not session.can_be_seen_by(request.user):
        if session.status == 'draft':
            messages.error(request, 'هذه الجلسة في مرحلة التحضير ولا يمكن الاطلاع عليها حالياً.')
        else:
            messages.error(request, 'ليس لديك صلاحية للاطلاع على الجلسات السابقة للمجلس.')
        return redirect('council:session_list')

    # Fetch all topics with related data in as few queries as possible
    topics = list(
        session.topics
        .select_related('session', 'created_by', 'decision', 'signed_decision', 'display_state')
        .prefetch_related('attachments', 'recordings', 'votes', 'votes__member', 'tables')
        .order_by('category', 'sub_order', 'order_number')
    )

    # Group topics by category preserving session categories order
    topics_by_category = []
    if request.user.is_super or request.user.can_view_topics:
        for cat in session.get_agenda_categories():
            cat_key = cat['key']
            cat_label = cat['label']
            cat_topics = [t for t in topics if t.category == cat_key]
            if cat_topics:
                theme = CATEGORY_THEMES.get(cat_key, DEFAULT_CUSTOM_THEME)
                topics_by_category.append({
                    'key': cat_key,
                    'label': cat_label,
                    'theme': theme,
                    'topics': cat_topics,
                })

    # Attendance list (evaluate once in memory to avoid 6 separate SQL queries)
    attendances = list(
        session.attendances
        .select_related('member', 'seat', 'proxy_user')
        .order_by('member__order', 'member__id')
    )
    attendances_primary = [
        a for a in attendances
        if a.status == 'present_primary' or (a.status == 'present' and not a.is_proxy)
    ]
    attendances_deputy = [
        a for a in attendances
        if a.status == 'present_deputy' or a.is_proxy
    ]
    attendances_excused = [a for a in attendances if a.status == 'excused']
    attendances_unexcused = [a for a in attendances if a.status in ('unexcused', 'absent')]
    attendances_unrecorded = [a for a in attendances if a.status == 'unrecorded']

    # Session stats (computed in memory from already-fetched topics)
    stats = {
        'total': len(topics),
        'voted': sum(1 for t in topics if t.status == 'voted'),
        'pending': sum(1 for t in topics if t.status == 'pending'),
    }

    editable = not session.is_frozen()
    next_stage = session.get_next_stage()
    user = request.user

    context = {
        'session':               session,
        'topics_by_category':    topics_by_category,
        'attendances':            attendances,
        'attendances_primary':    attendances_primary,
        'attendances_deputy':     attendances_deputy,
        'attendances_excused':    attendances_excused,
        'attendances_unexcused':  attendances_unexcused,
        'attendances_unrecorded': attendances_unrecorded,
        'stats':                 stats,
        'page_title':            f'الجلسة رقم {session.session_number}',
        'user_can_add':          user.can_add and editable,
        'user_can_edit':         user.can_edit and editable,
        'user_can_delete':       user.can_delete and editable,
        'user_can_add_session':       (user.is_super or user.can_add_session),
        'user_can_edit_session':      (user.is_super or user.can_edit_session) and editable,
        'user_can_delete_session':    (user.is_super or user.can_delete_session) and editable,
        'user_can_view_attendance':   (user.is_super or user.can_view_attendance or user.can_manage_attendance),
        'user_can_manage_attendance': (user.is_super or user.can_manage_attendance) and editable,
        'user_can_view_topics':       (user.is_super or user.can_view_topics),
        'user_can_add_topic':         (user.is_super or user.can_add_topic) and editable,
        'user_can_edit_topic':        (user.is_super or user.can_edit_topic) and editable,
        'user_can_delete_topic':      (user.is_super or user.can_delete_topic) and editable,
        'user_can_import_topics':     (user.is_super or user.can_import_topics) and editable,
        'user_can_export_minutes':    (user.is_super or user.can_export_minutes),
        'user_can_verify_integrity':  (user.is_super or user.can_verify_integrity),
        'user_can_view_live':         (user.is_super or user.can_view_live_session or user.can_start_session_live),
        'is_controller':              (user.is_super or user.can_start_session_live),
        'user_can_view_projector':    (user.is_super or user.can_view_projector),
        'user_can_view_analytics':    (user.is_super or user.can_view_analytics),
        'user_can_use_smart_reader':  (user.is_super or user.can_use_smart_reader),
        'user_can_vote':         user.can_vote and session.status == 'active',
        'user_can_draft':        user.can_draft_decision and editable,
        # Pass the user's own vote per topic as a dict {topic_pk: vote_obj}
        'user_votes': {
            t.pk: t.get_user_vote(user) for t in topics
        },
        # Lifecycle
        'session_stages':        session.get_stage_steps(),
        'session_frozen':        not editable,
        'next_stage':            next_stage,
        'next_stage_label':      STAGE_LABELS.get(next_stage, ''),
        'user_can_advance':      (user.is_super or user.can_advance_session_stage) and next_stage is not None,
        'user_can_reopen':       (user.is_super or user.can_reopen_frozen_session) and not editable,
        'user_can_view_stage_logs': (user.is_super or user.can_view_stage_logs),
        'stage_logs':            session.stage_logs.select_related('changed_by')[:10] if (user.is_super or user.can_view_stage_logs) else [],
        'session_recording':     SessionRecording.objects.filter(session=session).first(),
    }
    return render(request, 'council/session_detail.html', context)


# ── Session Create ─────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def session_create_view(request):
    """
    Create a new council session. Requires can_add_session.
    م2: if the previous session is not frozen, an approved request is required
    (unless the user holds «الموافقة على جلسة جديدة قبل إغلاق السابقة»).
    """
    if not (request.user.is_super or request.user.can_add_session):
        messages.error(request, 'ليس لديك صلاحية لإنشاء جلسات.')
        return redirect('/dashboard/')

    blocked, last_session, approved_request = _new_session_gate(request.user)
    if blocked and approved_request is None:
        pending = NewSessionRequest.objects.filter(requested_by=request.user, status='pending').first()
        if request.method == 'POST' and 'request_reason' in request.POST:
            reason = request.POST.get('request_reason', '').strip()
            if not reason:
                messages.error(request, 'يجب كتابة سبب طلب فتح جلسة جديدة.')
            elif pending:
                messages.info(request, 'لديك طلب قائم قيد المراجعة بالفعل.')
                return redirect('council:session_list')
            else:
                req = NewSessionRequest.objects.create(
                    previous_session=last_session, requested_by=request.user, reason=reason,
                )
                log_action(request.user, 'request', obj=req, request=request,
                           notes=f'طلب فتح جلسة جديدة قبل تجميد الجلسة رقم {last_session.session_number}: {reason}')
                messages.success(request, 'تم إرسال طلبك إلى صاحب صلاحية الموافقة، وستظهر النتيجة في صفحة الجلسات.')
                return redirect('council:session_list')
        return render(request, 'council/new_session_request.html', {
            'last_session': last_session,
            'pending':      pending,
            'page_title':   'طلب موافقة على فتح جلسة جديدة',
        })

    if request.method == 'POST':
        form = SessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.created_by = request.user
            session.status = 'draft'
            session.stage_changed_at = timezone.now()
            session.stage_changed_by = request.user
            session.save()
            if approved_request is not None:
                approved_request.used = True
                approved_request.save(update_fields=['used'])
            log_action(request.user, 'create', obj=session, request=request,
                       notes='إنشاء جلسة جديدة (مرحلة التحضير)')
            messages.success(request, f'تم إنشاء الجلسة رقم {session.session_number} بنجاح (مرحلة التحضير).')
            return redirect('council:session_detail', pk=session.pk)
    else:
        form = SessionForm()

    context = {
        'form':       form,
        'page_title': 'إنشاء جلسة جديدة',
        'action':     'create',
    }
    return render(request, 'council/session_form.html', context)


# ── Session Prepare (Agenda Builder – Dedicated Screen) ───────────────────────
# (Themes are imported centrally from council.models)


@login_required(login_url='/login/')
def session_prepare_view(request, pk=None):
    """
    الشاشة الموحدة الحصرية لإعداد جدول الأعمال.
    المرحلة A: إنشاء بيانات الجلسة أو تعديلها.
    المرحلة B (بعد الحفظ): عرض العناوين الرئيسية تفاعلياً مع أزرار إضافة المواضيع.
    تتطلب صلاحية can_prepare_agenda. تعمل فقط على جلسات في مرحلة draft.
    """
    user = request.user
    if not (user.is_super or user.can_prepare_agenda):
        messages.error(request, 'ليس لديك صلاحية للوصول إلى شاشة إعداد جدول الأعمال.')
        return redirect('council:session_list')

    session = None
    form_errors = None

    # ── Load existing session if pk provided ──
    if pk:
        session = get_object_or_404(CouncilSession, pk=pk)
        if session.status != 'draft':
            messages.error(request, 'لا يمكن تعديل جدول أعمال جلسة بعد مرحلة التحضير.')
            return redirect('council:session_detail', pk=pk)

    # ── POST: save session data (Phase A) ──
    if request.method == 'POST' and 'save_session' in request.POST:
        if session:
            form = SessionForm(request.POST, instance=session)
        else:
            # م2 gate check
            blocked, last_session, approved_request = _new_session_gate(user)
            if blocked and approved_request is None:
                messages.error(request, 'الجلسة السابقة لم تُغلق بعد. يرجى طلب موافقة مسبقة.')
                return redirect('council:session_list')
            form = SessionForm(request.POST)

        if form.is_valid():
            obj = form.save(commit=False)
            if not session:
                obj.created_by = user
                obj.status = 'draft'
                obj.stage_changed_at = timezone.now()
                obj.stage_changed_by = user
                if 'approved_request' in dir() and approved_request:
                    approved_request.used = True
                    approved_request.save(update_fields=['used'])
            obj.save()
            log_action(user, 'create' if not session else 'update', obj=obj, request=request,
                       notes='إعداد جدول الأعمال – حفظ بيانات الجلسة')
            messages.success(request, f'تم حفظ بيانات الجلسة رقم {obj.session_number} بنجاح.')
            return redirect('council:session_prepare_edit', pk=obj.pk)
        else:
            form_errors = form
            session = session  # keep existing

    # ── Build context ──
    if session:
        form = SessionForm(instance=session)
        categories = session.get_agenda_categories()
        all_topics = list(
            session.topics
            .prefetch_related('attachments', 'tables')
            .order_by('category', 'sub_order', 'order_number')
        )
        topics_by_category = {}
        for cat in categories:
            cat_key = cat['key']
            theme = CATEGORY_THEMES.get(cat_key, DEFAULT_CUSTOM_THEME)
            topics_by_category[cat_key] = {
                'label': cat['label'],
                'is_custom': cat.get('is_custom', False),
                'theme': theme,
                'topics': [t for t in all_topics if t.category == cat_key],
            }
        existing_keys = {cat['key'] for cat in categories}
        excluded_standard_categories = [
            {'key': k, 'label': l}
            for k, l in TOPIC_CATEGORIES
            if k not in existing_keys
        ]
    else:
        form = form_errors or SessionForm()
        topics_by_category = None
        excluded_standard_categories = []

    from council.models import TABLE_PRESET_CHOICES
    from council.views.table_views import PRESET_HEADERS_MAP, PRESET_SUM_COLS_MAP

    context = {
        'form':               form,
        'session':            session,
        'topics_by_category': topics_by_category,
        'topic_categories':   TOPIC_CATEGORIES,
        'excluded_standard_categories': excluded_standard_categories,
        'page_title':         'إعداد جدول الأعمال' if not session else f'إعداد جدول أعمال الجلسة رقم {session.session_number}',
        'phase':              'B' if session else 'A',
        'user_can_add_topic':    user.is_super or user.can_add_topic or getattr(user, 'can_prepare_agenda', False),
        'user_can_edit_topic':   user.is_super or user.can_edit_topic or getattr(user, 'can_prepare_agenda', False),
        'user_can_delete_topic': user.is_super or user.can_delete_topic or getattr(user, 'can_prepare_agenda', False),
        'user_can_upload':       user.is_super or user.can_upload_attachments or getattr(user, 'can_prepare_agenda', False),
        'user_can_add_table':    user.is_super or user.can_add_table or getattr(user, 'can_prepare_agenda', False),
        'preset_choices':        TABLE_PRESET_CHOICES,
        'presets_json':          json.dumps(PRESET_HEADERS_MAP, ensure_ascii=False),
        'preset_sum_cols_json':  json.dumps(PRESET_SUM_COLS_MAP, ensure_ascii=False),
    }
    return render(request, 'council/session_prepare.html', context)


# ── Session Edit ───────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def session_edit_view(request, pk):
    """
    Edit an existing session. Requires can_edit_session. Frozen sessions are blocked.
    """
    if not (request.user.is_super or request.user.can_edit_session):
        messages.error(request, 'ليس لديك صلاحية لتعديل الجلسات.')
        return redirect('/dashboard/')

    session = get_object_or_404(CouncilSession, pk=pk)
    if session.is_frozen():
        messages.error(request, 'هذه الجلسة مغلقة ومجمّدة ولا يمكن تعديلها.')
        return redirect('council:session_detail', pk=pk)

    if request.method == 'POST':
        form = SessionForm(request.POST, instance=session)
        if form.is_valid():
            changes = {
                f: {'old': str(form.initial.get(f, '')), 'new': str(form.cleaned_data.get(f, ''))}
                for f in form.changed_data
            }
            form.save()
            log_action(request.user, 'update', obj=session, field_changes=changes, request=request)
            messages.success(request, 'تم تحديث بيانات الجلسة بنجاح.')
            return redirect('council:session_detail', pk=session.pk)
    else:
        form = SessionForm(instance=session)

    context = {
        'form':       form,
        'session':    session,
        'page_title': f'تعديل الجلسة رقم {session.session_number}',
        'action':     'edit',
    }
    return render(request, 'council/session_form.html', context)


# ── Session Delete ─────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def session_delete_view(request, pk):
    """
    Delete a session (POST confirmation required). Requires can_delete_session.
    Frozen sessions cannot be deleted.
    """
    if not (request.user.is_super or request.user.can_delete_session):
        messages.error(request, 'ليس لديك صلاحية لحذف الجلسات.')
        return redirect('/dashboard/')

    session = get_object_or_404(CouncilSession, pk=pk)
    if session.is_frozen():
        messages.error(request, 'لا يمكن حذف جلسة مغلقة ومجمّدة.')
        return redirect('council:session_detail', pk=pk)

    if request.method == 'POST':
        session_number = session.session_number
        log_action(request.user, 'delete', obj=session, request=request,
                   notes=f'حذف الجلسة رقم {session_number}')
        session.delete()
        messages.success(request, f'تم حذف الجلسة رقم {session_number} بنجاح.')
        return redirect('council:session_list')

    context = {
        'session':    session,
        'page_title': f'حذف الجلسة رقم {session.session_number}',
    }
    return render(request, 'council/session_confirm_delete.html', context)


# ── Session Attendance ─────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def session_attendance_view(request, pk):
    """
    Manage attendance for all members in a session (5 visual colors + proxy support).
    GET:  Renders a list of all users with attendance status and seat mapping.
    POST: Saves the attendance with primary/deputy distinction.
    Requires can_manage_attendance. Frozen sessions are blocked.
    """
    if not (request.user.is_super or request.user.can_manage_attendance):
        messages.error(request, 'ليس لديك صلاحية لإدارة الحضور.')
        return redirect('/dashboard/')

    session = get_object_or_404(CouncilSession, pk=pk)
    if session.is_frozen():
        messages.error(request, 'هذه الجلسة مغلقة ومجمّدة ولا يمكن تعديل كشف حضورها.')
        return redirect('council:session_detail', pk=pk)

    from django.contrib.auth import get_user_model
    from council.models import EntitySeat
    UserModel = get_user_model()
    all_members = (
        UserModel.objects
        .filter(is_active=True, order__lt=100)
        .order_by('order', 'id')
    )

    seats_by_rep = {
        s.primary_rep_id: s for s in EntitySeat.objects.filter(is_active=True).select_related('deputy_rep_1', 'deputy_rep_2')
    }

    if request.method == 'POST':
        with transaction.atomic():
            for member in all_members:
                status = request.POST.get(f'status_{member.pk}', 'unrecorded')
                notes  = request.POST.get(f'notes_{member.pk}', '').strip()
                is_proxy = (status == 'present_deputy')
                proxy_name = request.POST.get(f'proxy_name_{member.pk}', '').strip()
                proxy_user_id = request.POST.get(f'proxy_user_{member.pk}')
                proxy_user = UserModel.objects.filter(pk=proxy_user_id, is_active=True).first() if proxy_user_id else None
                if proxy_user and not proxy_name:
                    proxy_name = proxy_user.full_name

                seat = seats_by_rep.get(member.pk)
                valid_statuses = ('present_primary', 'present_deputy', 'excused', 'unexcused', 'unrecorded', 'present')
                if status not in valid_statuses:
                    status = 'unrecorded'

                Attendance.objects.update_or_create(
                    session=session,
                    member=member,
                    defaults={
                        'seat': seat,
                        'status': status,
                        'is_proxy': is_proxy,
                        'proxy_user': proxy_user if is_proxy else None,
                        'proxy_name': proxy_name if is_proxy else '',
                        'member_title_snapshot': member.official_title or member.get_title_display(),
                        'notes': notes,
                        'attended_at': timezone.now() if status in ('present_primary', 'present_deputy', 'present') else None
                    },
                )
        log_action(request.user, 'update', obj=session, request=request, notes='تحديث كشف الحضور والغياب (المرحلة 2)')
        messages.success(request, 'تم حفظ سجل الحضور والغياب بنجاح.')
        return redirect('council:session_detail', pk=session.pk)

    # Build list of (member, attendance_or_None) pairs for template
    existing = {
        a.member_id: a
        for a in session.attendances.select_related('member', 'seat', 'proxy_user').all()
    }
    member_attendance = []
    for member in all_members:
        att = existing.get(member.pk)
        current_status = att.status if att else 'unrecorded'
        seat = seats_by_rep.get(member.pk)
        member_attendance.append({
            'member': member,
            'seat': seat,
            'status': current_status,
            'is_proxy': att.is_proxy if att else False,
            'proxy_user': att.proxy_user if att else None,
            'proxy_name': att.proxy_name if att else '',
            'notes': att.notes if att else '',
        })

    context = {
        'session':           session,
        'member_attendance': member_attendance,
        'page_title':        f'الحضور والغياب – الجلسة {session.session_number}',
        'status_choices': [
            ('present_primary', 'حاضر (أصيل)'),
            ('present_deputy',  'حاضر (إنابة)'),
            ('excused',         'غائب بعذر'),
            ('unexcused',       'غائب بغير عذر'),
            ('unrecorded',      'لم يُرصد بعد'),
        ],
    }
    return render(request, 'council/session_attendance.html', context)


# م1 – Session Lifecycle (5 stages) + Freezing / Reopening
# ══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/login/')
def session_advance_stage_view(request, pk):
    """
    Move a session to the next stage (POST only).
    Requires «نقل الجلسة بين المراحل». A backup is taken before freezing.
    """
    session = get_object_or_404(CouncilSession, pk=pk)
    if request.method != 'POST':
        return redirect('council:session_detail', pk=pk)

    if not (request.user.is_super or request.user.can_advance_session_stage):
        messages.error(request, 'ليس لديك صلاحية نقل مرحلة الجلسة.')
        return redirect('council:session_detail', pk=pk)

    next_stage = session.get_next_stage()
    if not next_stage:
        messages.warning(request, 'الجلسة في المرحلة النهائية (مغلقة ومجمّدة).')
        return redirect('council:session_detail', pk=pk)

    reason = request.POST.get('reason', '').strip()
    old_stage = session.status

    if next_stage == 'frozen':
        create_backup(request.user, f'قبل تجميد الجلسة رقم {session.session_number}')

    with transaction.atomic():
        session.status = next_stage
        session.stage_changed_at = timezone.now()
        session.stage_changed_by = request.user
        if next_stage == 'frozen':
            session.frozen_at = timezone.now()
            session.frozen_by = request.user
            session.document_hash = session.calculate_document_hash()
            session.hashed_at = timezone.now()
        session.save()
        SessionStageLog.objects.create(
            session=session, from_stage=old_stage, to_stage=next_stage,
            changed_by=request.user, reason=reason,
        )

    log_action(request.user, 'stage_change', obj=session, request=request,
               field_changes={'status': {'old': STAGE_LABELS.get(old_stage, old_stage),
                                         'new': STAGE_LABELS.get(next_stage, next_stage)}},
               notes=reason)

    # Phase 5: Trigger automated In-App & SMS notifications
    try:
        from council.services.notification_service import (
            notify_session_publishing, notify_session_live, notify_session_frozen
        )
        if next_stage == 'publishing':
            notify_session_publishing(session, sent_by=request.user)
        elif next_stage == 'active':
            notify_session_live(session, sent_by=request.user)
        elif next_stage == 'frozen':
            notify_session_frozen(session, sent_by=request.user)
    except Exception:
        pass

    messages.success(request, f'تم نقل الجلسة إلى مرحلة «{STAGE_LABELS.get(next_stage, next_stage)}» بنجاح.')
    return redirect('council:session_detail', pk=pk)


@login_required(login_url='/login/')
def session_reopen_view(request, pk):
    """
    Reopen a frozen session (POST only).
    Requires «إعادة فتح الجلسة المجمّدة» + password confirmation + reason.
    The session returns to the partial-close stage.
    """
    session = get_object_or_404(CouncilSession, pk=pk)
    if request.method != 'POST':
        return redirect('council:session_detail', pk=pk)

    if not session.is_frozen():
        messages.warning(request, 'الجلسة ليست مجمّدة.')
        return redirect('council:session_detail', pk=pk)

    if not (request.user.is_super or request.user.can_reopen_frozen_session):
        messages.error(request, 'ليس لديك صلاحية إعادة فتح الجلسة المجمّدة.')
        return redirect('council:session_detail', pk=pk)

    password = request.POST.get('password', '')
    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, 'يجب كتابة سبب إعادة الفتح.')
        return redirect('council:session_detail', pk=pk)

    if not request.user.check_password(password):
        log_action(request.user, 'reopen_fail', obj=session, request=request,
                   notes='محاولة إعادة فتح جلسة مجمّدة بكلمة مرور خاطئة')
        messages.error(request, 'كلمة المرور غير صحيحة. لم يتم فتح الجلسة.')
        return redirect('council:session_detail', pk=pk)

    old_stage = session.status
    with transaction.atomic():
        session.status = 'partial_close'
        session.reopen_reason = reason
        session.frozen_at = None
        session.frozen_by = None
        session.document_hash = ''
        session.hashed_at = None
        session.stage_changed_at = timezone.now()
        session.stage_changed_by = request.user
        session.save()
        SessionStageLog.objects.create(
            session=session, from_stage=old_stage, to_stage='partial_close',
            changed_by=request.user, reason=f'إعادة فتح: {reason}',
        )
    log_action(request.user, 'reopen', obj=session, request=request,
               field_changes={'status': {'old': STAGE_LABELS.get(old_stage, old_stage),
                                         'new': STAGE_LABELS['partial_close']}},
               notes=reason)
    messages.success(request, 'تمت إعادة فتح الجلسة وأُعيدت إلى مرحلة الإغلاق الجزئي.')
    return redirect('council:session_detail', pk=pk)


# ══════════════════════════════════════════════════════════════════════════════
# م2 – Review of new-session requests
# ══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/login/')
def new_session_request_review_view(request, pk):
    """Approve or reject a request to open a new session (POST only)."""
    req = get_object_or_404(NewSessionRequest, pk=pk)
    if request.method != 'POST':
        return redirect('council:session_list')
    if not _can_approve_new_session(request.user):
        messages.error(request, 'ليس لديك صلاحية البتّ في طلبات فتح الجلسات.')
        return redirect('council:session_list')
    if req.status != 'pending':
        messages.info(request, 'تم البتّ في هذا الطلب مسبقاً.')
        return redirect('council:session_list')

    decision = request.POST.get('decision')
    if decision not in ('approve', 'reject'):
        return redirect('council:session_list')

    req.status = 'approved' if decision == 'approve' else 'rejected'
    req.reviewed_by = request.user
    req.reviewed_at = timezone.now()
    req.review_notes = request.POST.get('review_notes', '').strip()
    req.save()
    log_action(request.user, decision, obj=req, request=request, notes=req.review_notes)
    messages.success(request, 'تمت الموافقة على الطلب.' if decision == 'approve' else 'تم رفض الطلب.')
    return redirect('council:session_list')


# ══════════════════════════════════════════════════════════════════════════════
# م11 – Audit Log + Backups
# ══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/login/')
def audit_log_view(request):
    """Read-only audit log with filters. Requires «عرض سجل الرقابة»."""
    if not request.user.can_view_audit_log:
        messages.error(request, 'ليس لديك صلاحية لعرض سجل الرقابة.')
        return redirect('/dashboard/')

    logs = AuditLog.objects.select_related('user').order_by('-timestamp')

    action_filter = request.GET.get('action', '')
    user_filter = request.GET.get('user', '').strip()
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if action_filter:
        logs = logs.filter(action=action_filter)
    if user_filter:
        logs = logs.filter(user__full_name__icontains=user_filter)
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    page_obj = Paginator(logs, 30).get_page(request.GET.get('page', 1))

    from council.models import SystemAuditControl
    audit_control = SystemAuditControl.get_setting()

    context = {
        'page_obj':              page_obj,
        'action_filter':         action_filter,
        'user_filter':           user_filter,
        'date_from':             date_from,
        'date_to':               date_to,
        'action_choices':        AuditLog.ACTION_CHOICES,
        'backups':               BackupLog.objects.select_related('created_by')[:10],
        'page_title':            'سجل رقابة المستخدمين',
        'audit_control':         audit_control,
        'user_can_toggle_audit': (request.user.is_super or request.user.can_toggle_audit_backup),
        'user_can_clear_audit':  (request.user.is_super or request.user.can_clear_audit_log),
    }
    return render(request, 'council/audit_log.html', context)


@login_required(login_url='/login/')
def backup_now_view(request):
    """Manual backup (POST only) – super admin only."""
    if request.method == 'POST' and request.user.is_super:
        out = create_backup(request.user, 'يدوي من الواجهة')
        log_action(request.user, 'backup', request=request, notes=str(out or 'فشل'))
        if out:
            messages.success(request, 'تم إنشاء نسخة احتياطية بنجاح.')
        else:
            messages.error(request, 'فشل إنشاء النسخة الاحتياطية.')
    return redirect('council:audit_log')


@login_required(login_url='/login/')
def toggle_audit_backup_view(request):
    """Toggle Audit Logging and Automated Backup on/off."""
    if request.method != 'POST':
        return redirect('council:audit_log')
    if not (request.user.is_super or request.user.can_toggle_audit_backup):
        messages.error(request, 'عذراً، ليس لديك صلاحية للتحكم في إيقاف أو تشغيل نظام الرقابة والنسخ الاحتياطي.')
        return redirect('council:audit_log')

    from council.models import SystemAuditControl
    control = SystemAuditControl.get_setting()
    control.is_enabled = not control.is_enabled
    control.updated_by = request.user
    control.save(update_fields=['is_enabled', 'updated_by', 'updated_at'])

    if control.is_enabled:
        messages.success(request, 'تم استئناف وتشغيل نظام رقابة المستخدمين والنسخ الاحتياطي بنجاح.')
    else:
        messages.warning(request, 'تم إيقاف نظام رقابة المستخدمين والنسخ الاحتياطي بشكل صارم وفوري.')

    return redirect('council:audit_log')


@login_required(login_url='/login/')
def clear_audit_log_view(request):
    """Purge all user audit logs and backup logs & physical backup files permanently."""
    if request.method != 'POST':
        return redirect('council:audit_log')
    if not (request.user.is_super or request.user.can_clear_audit_log):
        messages.error(request, 'عذراً، ليس لديك صلاحية لتصفير ومسح سجلات الرقابة والنسخ الاحتياطي.')
        return redirect('council:audit_log')

    from council.models import AuditLog, BackupLog
    audit_count, _ = AuditLog.objects.all().delete()
    backup_count, _ = BackupLog.objects.all().delete()

    deleted_files_count = 0
    try:
        from django.conf import settings
        from pathlib import Path
        backup_dir = Path(settings.BASE_DIR) / 'backups'
        if backup_dir.exists():
            for f in backup_dir.glob('db_backup_*.*'):
                try:
                    f.unlink()
                    deleted_files_count += 1
                except Exception:
                    pass
    except Exception:
        pass

    messages.success(
        request,
        f'تم بنجاح التصفير الشامل والنهائي: تم مسح {audit_count} سجل رقابة مستخدمين، و{backup_count} سجل نسخ احتياطي، وحذف {deleted_files_count} ملف نسخة احتياطية من الخادم.'
    )
    return redirect('council:audit_log')
