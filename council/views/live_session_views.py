# -*- coding: utf-8 -*-
"""
Live Session Views & Real-time Cockpit
University Council Management System - Phase 3

Handles:
- Live Session Interactive Cockpit (session_live_view)
- Big Screen / Projector Mode (session_projector_view)
- Post-Session Analytics Dashboard (session_analytics_view)
- Topic Display State & Voting Gatekeeper APIs
- Countdown Timer APIs
- Speech Queue (SpeakRequest) APIs
- Audio Recording (Chunked Upload & Offset Indexing) APIs
- Exit Permits (Formal Leave) APIs
- Quorum Real-time Tracking API
"""
import os
import json
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, Count, Sum
from django.http import JsonResponse, HttpResponseForbidden, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from council.models import (
    CouncilSession, Topic, Vote, EntitySeat, Attendance,
    TopicDisplayState, SpeakRequest, SessionRecording, ExitPermit,
    LiveSessionPresence, TOPIC_CATEGORIES, user_can_view_drafts
)


def user_can_control_live(user, session=None):
    """
    Check if the authenticated user has permission to control live session:
    - If session is provided:
        1. President of the session ALWAYS has sovereign control.
        2. Delegated live_controller has active control granted by the President.
        3. Super Admin has control if no conflict.
        4. Other users with can_start_session_live remain FROZEN until enabled by President.
    - If session is None:
        Generic permission check for navigation/menu.
    """
    if not user or not user.is_authenticated:
        return False
    if session is not None:
        return session.user_can_manage_live_controls(user)
    if getattr(user, 'is_super', False):
        return True
    return bool(getattr(user, 'can_start_session_live', False))


# ── 1. Live Session Cockpit View ──────────────────────────────────────────────
@login_required(login_url='/login/')
def session_live_view(request, session_pk):
    """
    Interactive Live Session Cockpit.
    Requires can_view_live_session or can_start_session_live.
    """
    user = request.user
    if not (user.is_super or user.can_view_live_session or user.can_start_session_live):
        messages.error(request, 'ليس لديك صلاحية لدخول شاشة الانعقاد الحي.')
        return redirect('/dashboard/')

    session = get_object_or_404(CouncilSession, pk=session_pk)

    if not session.can_be_seen_by(user):
        messages.error(request, 'لا يمكنك استعراض هذه الجلسة.')
        return redirect('/dashboard/')

    # ── Manager Presence Tracking in Live Session ──
    if user.is_super or user.can_start_session_live:
        LiveSessionPresence.objects.update_or_create(
            session=session, user=user,
            defaults={'last_seen': timezone.now(), 'is_active': True}
        )

    is_president = session.is_user_president(user)
    is_controller = session.user_can_manage_live_controls(user)
    is_delegated = bool(session.live_controller_id and session.live_controller_id == user.pk)
    is_frozen_manager = bool((user.is_super or user.can_start_session_live) and not is_controller)

    # Online Managers List for the President's Command Panel
    presence_cutoff = timezone.now() - timezone.timedelta(minutes=10)
    manager_presences = (
        LiveSessionPresence.objects.filter(session=session)
        .select_related('user')
        .order_by('-last_seen')
    )
    online_managers = []
    for p in manager_presences:
        if session.is_user_president(p.user):
            continue
        is_online = (p.last_seen >= presence_cutoff) and p.is_active
        online_managers.append({
            'id': p.user.pk,
            'name': p.user.full_name,
            'title': p.user.official_title or p.user.get_title_display(),
            'avatar_initials': getattr(p.user, 'avatar_initials', '') or p.user.full_name[:2],
            'is_online': is_online,
            'is_delegated': bool(session.live_controller_id == p.user.pk),
            'last_seen': p.last_seen.strftime('%H:%M:%S'),
        })

    # Fetch topics once with all related objects prefetched
    raw_topics = list(
        session.topics
        .select_related('session', 'display_state', 'decision')
        .prefetch_related('tables', 'votes', 'votes__member', 'recordings', 'attachments')
        .order_by('sub_order', 'order_number', 'id')
    )
    created_any_state = False
    for t in raw_topics:
        if not hasattr(t, 'display_state') or t.display_state is None:
            TopicDisplayState.objects.get_or_create(topic=t)
            created_any_state = True

    if created_any_state:
        raw_topics = list(
            session.topics
            .select_related('session', 'display_state', 'decision')
            .prefetch_related('tables', 'votes', 'votes__member', 'recordings', 'attachments')
            .order_by('sub_order', 'order_number', 'id')
        )
    cat_order_map = {cat_key: idx for idx, (cat_key, _) in enumerate(TOPIC_CATEGORIES)}
    topics = sorted(raw_topics, key=lambda t: (cat_order_map.get(t.category, 99), t.sub_order, t.order_number, t.id))

    # Attach user vote & decision info
    for t in topics:
        t.user_vote = t.get_user_vote(user)
        t.has_decision_flag = t.has_decision()
        t.decision_text_val = t.decision.decision_text if t.has_decision_flag else ''

    # ── Intelligent Active Topic Resolution (Preserves President's exact position) ──
    topics_map = {t.pk: t for t in topics}
    active_topic = None

    # 1. URL parameter override (e.g. returning directly from global banner: ?topic=123)
    req_topic_id = request.GET.get('topic')
    if req_topic_id and req_topic_id.isdigit():
        req_id = int(req_topic_id)
        if req_id in topics_map:
            active_topic = topics_map[req_id]

    # 2. Check if any topic is actively in 'shown' or 'voting' state on the floor
    if not active_topic:
        for t in topics:
            if t.display_state.display_status in ('shown', 'voting'):
                active_topic = t
                break

    # 3. Check session's remembered last_active_topic
    if not active_topic and session.last_active_topic_id and session.last_active_topic_id in topics_map:
        active_topic = topics_map[session.last_active_topic_id]

    # 4. If none, find the first upcoming topic that is not closed/voted yet
    if not active_topic and topics:
        for t in topics:
            if t.status not in ('voted', 'closed') and t.display_state.display_status != 'closed' and not t.has_decision_flag:
                active_topic = t
                break

    # 5. Fallback to first topic if all else fails
    if not active_topic and topics:
        active_topic = topics[0]

    completed_topics_count = sum(
        1 for t in topics
        if t.status in ('voted', 'closed') or t.display_state.display_status == 'closed' or t.has_decision_flag
    )
    total_topics_count = len(topics)
    progress_pct = round((completed_topics_count / total_topics_count) * 100) if total_topics_count else 0

    topics_by_category = []
    for cat_key, cat_label in TOPIC_CATEGORIES:
        cat_topics = [t for t in topics if t.category == cat_key]
        if cat_topics:
            has_active = any((active_topic and t.pk == active_topic.pk) or t.display_state.display_status in ('shown', 'voting') for t in cat_topics)
            topics_by_category.append({
                'key': cat_key,
                'label': cat_label,
                'topics': cat_topics,
                'has_active': has_active,
            })

    # Quorum Info
    quorum_info = session.get_quorum_info()

    # User Seat
    user_seat = EntitySeat.objects.filter(
        Q(primary_rep=user) | Q(deputy_rep_1=user) | Q(deputy_rep_2=user),
        is_active=True
    ).first()

    # Speech Queue
    active_speaker = SpeakRequest.objects.filter(
        session=session, status='speaking'
    ).select_related('member', 'seat', 'topic').first()

    pending_speakers = SpeakRequest.objects.filter(
        session=session, status='pending'
    ).select_related('member', 'seat', 'topic').order_by('requested_at')

    completed_speakers = SpeakRequest.objects.filter(
        session=session, status='completed'
    ).select_related('member', 'seat').order_by('-completed_at')[:5]

    user_pending_speak = SpeakRequest.objects.filter(
        session=session, member=user, status='pending'
    ).first()

    # Exit Permits
    user_exit_permit = ExitPermit.objects.filter(
        session=session, member=user
    ).first()

    pending_exit_permits = ExitPermit.objects.filter(
        session=session, status='pending'
    ).select_related('member', 'seat')

    can_view_attendance = bool(user.is_super or user.can_view_attendance or user.can_manage_attendance or is_controller)

    # Real-time attendance list for in-cockpit attendance modal
    attendance_list = []
    if can_view_attendance:
        existing_att = {
            a.member_id: a
            for a in session.attendances.select_related('member', 'seat', 'proxy_user').all()
        }
        from accounts.models import User as CouncilUserModel
        all_council_members = CouncilUserModel.objects.filter(is_active=True).exclude(title='مدير_النظام').order_by('order', 'id')
        for m in all_council_members:
            att = existing_att.get(m.pk)
            attendance_list.append({
                'member': m,
                'seat': att.seat if att else None,
                'status': att.status if att else 'unrecorded',
                'status_display': att.get_status_display() if att else 'لم يُرصد',
                'is_proxy': att.is_proxy if att else False,
                'proxy_name': att.proxy_name if att else '',
            })

    recording = SessionRecording.objects.filter(session=session).first()

    context = {
        'session': session,
        'can_view_attendance': can_view_attendance,
        'attendance_list': attendance_list,
        'topics': topics,
        'topics_by_category': topics_by_category,
        'active_topic': active_topic,
        'completed_topics_count': completed_topics_count,
        'total_topics_count': total_topics_count,
        'progress_pct': progress_pct,
        'is_president': is_president,
        'is_delegated': is_delegated,
        'is_frozen_manager': is_frozen_manager,
        'is_controller': is_controller,
        'can_start_session_live': is_controller,
        'active_controller': session.live_controller,
        'online_managers': online_managers,
        'online_managers_count': len([m for m in online_managers if m['is_online']]),
        'chair_user': session.get_chair_user(),
        'chair_display_name': session.get_chair_display_name(),
        'can_set_topic_timer': is_controller,
        'can_suspend_session': is_controller,
        'can_postpone_topic': is_controller,
        'is_suspended': getattr(session, 'is_suspended', False),
        'suspension_reason': getattr(session, 'suspension_reason', ''),
        'can_draft_decision': (is_controller or user.can_draft_decision) and not session.is_frozen(),
        'can_manage_speak_requests': is_controller or (user.is_super and not session.live_controller_id),
        'can_request_speak': user.is_super or user.can_request_speak,
        'can_control_recording': is_controller or user.can_control_recording,
        'can_request_exit_permit': user.is_super or user.can_request_exit_permit,
        'can_approve_exit_permit': is_controller or user.can_approve_exit_permit,
        'can_vote': user.is_super or user.can_vote,
        'can_view_projector': user.is_super or user.can_view_projector,
        'can_view_analytics': user.is_super or user.can_view_analytics,
        'quorum_info': quorum_info,
        'user_seat': user_seat,
        'active_speaker': active_speaker,
        'pending_speakers': pending_speakers,
        'completed_speakers': completed_speakers,
        'user_pending_speak': user_pending_speak,
        'user_exit_permit': user_exit_permit,
        'pending_exit_permits': pending_exit_permits,
        'recording': recording,
    }
    return render(request, 'council/session_live.html', context)


# ── 2. Projector Mode (Big Screen in Hall) ────────────────────────────────────
@login_required(login_url='/login/')
def session_projector_view(request, session_pk):
    """
    Projector / Screen display mode designed for hall projectors and wall displays.
    Requires can_view_projector permission.
    """
    if not (request.user.is_super or request.user.can_view_projector):
        messages.error(request, 'ليس لديك صلاحية لفتح شاشة العرض الكلي (البروجيكتور).')
        return redirect('/dashboard/')

    session = get_object_or_404(CouncilSession, pk=session_pk)

    if not session.can_be_seen_by(request.user):
        messages.error(request, 'لا يمكن عرض هذه الجلسة.')
        return redirect('/dashboard/')

    # Find active topic
    active_topic = None
    for t in session.topics.select_related('display_state').all():
        if hasattr(t, 'display_state') and t.display_state.display_status in ('shown', 'voting', 'closed'):
            if not active_topic or t.display_state.display_status in ('voting', 'shown'):
                active_topic = t

    if not active_topic:
        active_topic = session.topics.first()

    active_speaker = SpeakRequest.objects.filter(
        session=session, status='speaking'
    ).select_related('member', 'seat').first()

    quorum_info = session.get_quorum_info()

    context = {
        'session': session,
        'active_topic': active_topic,
        'active_speaker': active_speaker,
        'quorum_info': quorum_info,
    }
    return render(request, 'council/session_projector.html', context)


# ── 3. Post-Session Analytics Dashboard ───────────────────────────────────────
@login_required(login_url='/login/')
def session_analytics_view(request, session_pk):
    """
    Comprehensive analytical report post-session:
    Topic duration, speak request stats, quorum retention, voting consensus.
    Requires can_view_analytics permission.
    """
    if not (request.user.is_super or request.user.can_view_analytics):
        messages.error(request, 'ليس لديك صلاحية لعرض لوحة إحصائيات وتحليلات الجلسة.')
        return redirect('/dashboard/')

    session = get_object_or_404(CouncilSession, pk=session_pk)
    if not session.can_be_seen_by(request.user):
        messages.error(request, 'لا يمكن عرض إحصائيات هذه الجلسة.')
        return redirect('/dashboard/')

    topics = list(
        session.topics
        .select_related('session', 'display_state', 'decision')
        .prefetch_related('votes')
        .all()
    )
    total_topics = len(topics)
    voted_topics = sum(1 for t in topics if t.status == 'voted')
    total_votes = sum(len(t.votes.all()) for t in topics)

    # Speaking statistics
    completed_speeches = list(
        SpeakRequest.objects
        .filter(session=session, status='completed')
        .select_related('member', 'seat')
    )
    total_speakers_count = len({sr.member_id for sr in completed_speeches})
    total_speeches = len(completed_speeches)

    total_speaking_seconds = 0
    speaker_stats = {}
    speeches_by_topic = {}
    for sr in completed_speeches:
        dur = sr.get_duration_seconds()
        total_speaking_seconds += dur
        m_name = sr.member.full_name
        s_name = sr.seat.name if sr.seat else (sr.member.department or 'عضو مجلس')
        if m_name not in speaker_stats:
            speaker_stats[m_name] = {'count': 0, 'duration': 0, 'seat': s_name, 'member': sr.member}
        speaker_stats[m_name]['count'] += 1
        speaker_stats[m_name]['duration'] += dur
        if sr.topic_id:
            speeches_by_topic[sr.topic_id] = speeches_by_topic.get(sr.topic_id, 0) + 1

    speaker_ranking = sorted(speaker_stats.values(), key=lambda x: x['duration'], reverse=True)

    # Quorum & Attendance Breakdown
    quorum_info = session.get_quorum_info()
    exit_permits = ExitPermit.objects.filter(session=session).select_related('member', 'seat')

    # Recording info
    recording = getattr(session, 'recording', None)

    # Topics performance table
    topic_analytics = []
    for t in topics:
        state = getattr(t, 'display_state', None)
        v_summary = t.get_vote_summary()
        t_speeches = speeches_by_topic.get(t.pk, 0)
        topic_analytics.append({
            'topic': t,
            'state': state,
            'vote_summary': v_summary,
            'speeches_count': t_speeches,
            'percentages': state.get_vote_percentages() if state else {},
        })

    context = {
        'session': session,
        'total_topics': total_topics,
        'voted_topics': voted_topics,
        'total_votes': total_votes,
        'total_speakers_count': total_speakers_count,
        'total_speeches': total_speeches,
        'total_speaking_seconds': total_speaking_seconds,
        'total_speaking_minutes': round(total_speaking_seconds / 60, 1),
        'speaker_ranking': speaker_ranking,
        'quorum_info': quorum_info,
        'exit_permits': exit_permits,
        'recording': recording,
        'topic_analytics': topic_analytics,
    }
    return render(request, 'council/session_analytics.html', context)


# ==============================================================================
# AJAX / JSON API ENDPOINTS
# ==============================================================================

# ── Topic Live Control API ───────────────────────────────────────────────────
@login_required(login_url='/login/')
@require_POST
def api_topic_control(request, topic_pk):
    """
    Allows authorized user to:
    - show topic / hide topic / open_voting / close_voting (requires can_start_session_live)
    - set_timer / stop_timer (requires can_set_topic_timer or can_start_session_live)
    - save_decision (requires can_draft_decision or can_start_session_live)
    """
    try:
        data = json.loads(request.body) if request.body else request.POST
    except Exception:
        data = request.POST

    action = data.get('action')
    user = request.user

    topic = get_object_or_404(Topic.objects.select_related('session'), pk=topic_pk)
    session = topic.session

    # Strict live control gatekeeper: tools must be authorized by the President
    if not session.user_can_manage_live_controls(user):
        return JsonResponse({
            'ok': False,
            'error': 'أدوات التحكم بالجلسة الحية مجمدة حالياً بانتظار تمكين رئيس الجلسة.'
        }, status=403)

    if action in ('set_timer', 'stop_timer'):
        if not (user.is_super or user.can_set_topic_timer or session.user_can_manage_live_controls(user)):
            return JsonResponse({'ok': False, 'error': 'ليس لديك صلاحية لضبط المؤقت الزمني للمواضيع.'}, status=403)
    elif action in ('suspend_topic', 'postpone_topic'):
        if not (user.is_super or getattr(user, 'can_postpone_suspend_topic', False) or session.user_can_manage_live_controls(user)):
            return JsonResponse({'ok': False, 'error': 'ليس لديك صلاحية لتعليق أو تأجيل مواضيع جدول الأعمال.'}, status=403)
    elif action == 'save_decision':
        if not (user.is_super or user.can_draft_decision or session.user_can_manage_live_controls(user)):
            return JsonResponse({'ok': False, 'error': 'ليس لديك صلاحية لصياغة أو اعتماد القرار.'}, status=403)
    else:
        if not session.user_can_manage_live_controls(user):
            return JsonResponse({'ok': False, 'error': 'غير مصرح لك بالتحكم بالجلسة الحية.'}, status=403)

    state = topic.get_display_state()
    folded_topic_ids = []

    with transaction.atomic():
        if action == 'show':
            # Auto-hide any other currently 'shown' topics in this session so only 1 topic is active on the floor
            other_shown = TopicDisplayState.objects.filter(
                topic__session_id=topic.session_id,
                display_status='shown'
            ).exclude(topic_id=topic.pk)
            folded_topic_ids = list(other_shown.values_list('topic_id', flat=True))
            if folded_topic_ids:
                other_shown.update(display_status='hidden')

            state.display_status = 'shown'
            state.save()
            topic.status = 'discussing'
            topic.save(update_fields=['status'])
            msg = 'تم عرض الموضوع للنقاش على المنصة.'

        elif action == 'hide':
            state.display_status = 'hidden'
            state.save()
            msg = 'تم طي الموضوع.'

        elif action == 'suspend_topic':
            state.display_status = 'suspended'
            state.timer_started_at = None
            state.save()
            topic.status = 'suspended'
            topic.suspended_at = timezone.now()
            topic.save(update_fields=['status', 'suspended_at'])
            msg = f'تم تعليق الموضوع «{topic.title}» مؤقتاً ويمكن العودة إليه في أي وقت.'

        elif action == 'postpone_topic':
            postpone_reason = (data.get('reason') or '').strip()
            postponed_to = (data.get('postponed_to') or 'الجلسة القادمة').strip()
            state.display_status = 'closed'
            state.timer_started_at = None
            state.save()
            topic.status = 'postponed'
            topic.postpone_reason = postpone_reason
            topic.postponed_to = postponed_to
            topic.save(update_fields=['status', 'postpone_reason', 'postponed_to'])
            msg = f'تم تأجيل الموضوع «{topic.title}» رسمياً إلى {postponed_to}.'

        elif action == 'open_voting':
            other_shown = TopicDisplayState.objects.filter(
                topic__session_id=topic.session_id,
                display_status='shown'
            ).exclude(topic_id=topic.pk)
            folded_topic_ids = list(other_shown.values_list('topic_id', flat=True))
            if folded_topic_ids:
                other_shown.update(display_status='hidden')

            state.display_status = 'voting'
            state.voting_opened_at = timezone.now()
            state.voting_opened_by = request.user
            state.save()
            topic.status = 'discussing'
            topic.save(update_fields=['status'])
            msg = 'تم فتح باب التصويت على الموضوع.'

        elif action == 'close_voting':
            state.display_status = 'closed'
            state.voting_closed_at = timezone.now()
            state.voting_closed_by = request.user
            state.save()
            topic.status = 'voted'
            topic.save(update_fields=['status'])
            msg = 'تم إغلاق التصويت واحتساب النتائج.'

        elif action == 'set_timer':
            raw_mins = int(data.get('minutes', 5))
            if raw_mins <= 0:
                state.timer_started_at = None
                state.allocated_minutes = 0
                state.save()
                msg = 'تم إيقاف المؤقت.'
            else:
                state.allocated_minutes = raw_mins
                state.timer_started_at = timezone.now()
                state.save()
                msg = f'تم ضبط المؤقت لمناقشة الموضوع لمدة {raw_mins} دقائق.'

        elif action == 'stop_timer':
            state.timer_started_at = None
            state.allocated_minutes = 0
            state.save()
            msg = 'تم إيقاف المؤقت.'

        elif action == 'save_decision':
            from council.models import Decision
            decision_text = (data.get('decision_text') or '').strip()
            if not decision_text:
                return JsonResponse({'ok': False, 'error': 'يرجى كتابة نص القرار قبل الاعتماد.'}, status=400)
            Decision.objects.update_or_create(
                topic=topic,
                defaults={
                    'decision_text': decision_text,
                    'drafted_by': request.user,
                }
            )
            if topic.status == 'pending':
                topic.status = 'closed'
                topic.save(update_fields=['status'])
            msg = 'تم اعتماد وحفظ قرار المجلس لهذا الموضوع بنجاح.'

        else:
            return JsonResponse({'ok': False, 'error': 'إجراء غير معروف.'}, status=400)

        # Update last_active_topic on session to persist active position
        if action in ('show', 'open_voting', 'close_voting', 'set_timer', 'save_decision', 'suspend_topic', 'postpone_topic'):
            if topic.session.last_active_topic_id != topic.pk:
                topic.session.last_active_topic = topic
                topic.session.save(update_fields=['last_active_topic'])

    summary = topic.get_vote_summary()
    percentages = state.get_vote_percentages()
    has_dec = topic.has_decision()
    dec_text = topic.decision.decision_text if has_dec else ''

    return JsonResponse({
        'ok': True,
        'message': msg,
        'topic_id': topic.pk,
        'topic_status': topic.status,
        'folded_topic_ids': folded_topic_ids,
        'display_status': state.display_status,
        'display_status_label': state.get_display_status_display(),
        'allocated_minutes': state.allocated_minutes,
        'remaining_seconds': state.get_remaining_seconds(),
        'is_voting_open': state.display_status == 'voting',
        'summary': summary,
        'percentages': percentages,
        'has_decision': has_dec,
        'decision_text': dec_text,
        'postponed_to': getattr(topic, 'postponed_to', ''),
        'postpone_reason': getattr(topic, 'postpone_reason', ''),
    })


# ── Session Lifecycle Control API (Suspend / Resume / Adjourn) ────────────────
@login_required(login_url='/login/')
@require_POST
def api_session_lifecycle_control(request, session_pk):
    """
    Allows President or authorized users with can_suspend_resume_session to:
    - suspend: recess the session, pause recording/timer, release member lockdown
    - resume: resume the session, restore lockdown and deliberations
    - adjourn: formally close live deliberations, move to partial_close stage
    """
    user = request.user
    session = get_object_or_404(CouncilSession, pk=session_pk)

    try:
        data = json.loads(request.body) if request.body else request.POST
    except Exception:
        data = request.POST

    action = data.get('action')

    if not session.user_can_manage_live_controls(user):
        return JsonResponse({'ok': False, 'error': 'أدوات تعليق أو رفع الجلسة مجمدة حالياً بانتظار تمكين رئيس الجلسة.'}, status=403)

    if action in ('suspend', 'resume'):
        if not (user.is_super or getattr(user, 'can_suspend_resume_session', False) or session.user_can_manage_live_controls(user)):
            return JsonResponse({'ok': False, 'error': 'غير مصرح لك بتعليق أو استئناف الجلسة.'}, status=403)
    elif action == 'adjourn':
        if not (user.is_super or getattr(user, 'can_suspend_resume_session', False) or user.can_advance_session_stage or session.user_can_manage_live_controls(user)):
            return JsonResponse({'ok': False, 'error': 'غير مصرح لك برفع أو إنهاء الجلسة.'}, status=403)
    else:
        return JsonResponse({'ok': False, 'error': 'إجراء غير معروف.'}, status=400)

    with transaction.atomic():
        if action == 'suspend':
            reason = (data.get('reason') or 'استراحة مؤقتة للجلسة').strip()
            session.is_suspended = True
            session.suspended_at = timezone.now()
            session.suspension_reason = reason
            session.save(update_fields=['is_suspended', 'suspended_at', 'suspension_reason'])

            # Pause continuous recording if active and unpaused
            rec = getattr(session, 'recording', None)
            if rec and rec.started_at and not rec.ended_at and not rec.is_paused:
                rec.is_paused = True
                rec.paused_at = timezone.now()
                rec.save(update_fields=['is_paused', 'paused_at'])

            msg = f'تم تعليق الجلسة مؤقتاً ({reason})، وفُك قيد شاشات الأعضاء بنجاح.'
            return JsonResponse({'ok': True, 'action': 'suspend', 'is_suspended': True, 'reason': reason, 'message': msg})

        elif action == 'resume':
            session.is_suspended = False
            session.resumed_at = timezone.now()
            session.save(update_fields=['is_suspended', 'resumed_at'])
            msg = 'تم استئناف انعقاد الجلسة الحية وإعادة تفعيل قاعة المداولات بنجاح.'
            return JsonResponse({'ok': True, 'action': 'resume', 'is_suspended': False, 'message': msg})

        elif action == 'adjourn':
            from council.models import SessionStageLog, STAGE_LABELS
            old_stage = session.status
            session.status = 'partial_close'
            session.is_suspended = False
            session.end_time = timezone.localtime().time()
            session.stage_changed_at = timezone.now()
            session.stage_changed_by = request.user
            session.save(update_fields=['status', 'is_suspended', 'end_time', 'stage_changed_at', 'stage_changed_by'])

            # Stop recording if running
            rec = getattr(session, 'recording', None)
            if rec and rec.started_at and not rec.ended_at:
                rec.ended_at = timezone.now()
                rec.is_paused = False
                rec.save(update_fields=['ended_at', 'is_paused'])

            SessionStageLog.objects.create(
                session=session, from_stage=old_stage, to_stage='partial_close',
                changed_by=request.user, reason='رفع الجلسة وإنهاء المداولات الحية من شاشة القاعة',
            )

            msg = 'تم رفع الجلسة وتوثيق وقت الانتهاء بنجاح. تم نقل الجلسة إلى مرحلة صياغة واعتماد القرارات.'
            return JsonResponse({
                'ok': True,
                'action': 'adjourn',
                'status': 'partial_close',
                'redirect_url': f'/sessions/{session.pk}/',
                'message': msg
            })


# ── Dynamic Session Control Delegation API (President & Co-Pilot) ────────────
@login_required(login_url='/login/')
@require_POST
def api_session_delegate_control(request, session_pk):
    """
    Allows the Council President (or Super Admin) to:
    - 'delegate': dynamically grant active control to an online manager
    - 'revoke': freeze all delegates and reclaim exclusive sovereign control for the President
    """
    user = request.user
    session = get_object_or_404(CouncilSession, pk=session_pk)

    if not (session.is_user_president(user) or user.is_super):
        return JsonResponse({
            'ok': False,
            'error': 'عذراً، حق تفويض وإدارة صلاحيات الجلسة محصور حصراً برئيس الجلسة.'
        }, status=403)

    try:
        data = json.loads(request.body) if request.body else request.POST
    except Exception:
        data = request.POST

    action = data.get('action')

    with transaction.atomic():
        if action == 'delegate':
            target_user_id = data.get('user_id') or data.get('manager_id')
            if not target_user_id:
                return JsonResponse({'ok': False, 'error': 'معرف المستخدم المطلوب تفويضه مفقود.'}, status=400)
            from django.contrib.auth import get_user_model
            UserModel = get_user_model()
            target_user = get_object_or_404(UserModel, pk=target_user_id)

            session.live_controller = target_user
            session.live_controller_delegated_at = timezone.now()
            session.save(update_fields=['live_controller', 'live_controller_delegated_at'])

            return JsonResponse({
                'ok': True,
                'action': 'delegate',
                'controller_id': target_user.pk,
                'controller_name': target_user.full_name,
                'controller_title': target_user.official_title or target_user.get_title_display(),
                'message': f'تم تفويض إدارة الجلسة بنجاح إلى: {target_user.full_name}.'
            })

        elif action == 'revoke':
            prev = session.live_controller
            session.live_controller = None
            session.live_controller_delegated_at = None
            session.save(update_fields=['live_controller', 'live_controller_delegated_at'])

            msg = 'تم استعادة التحكم الحصري وتجميد أدوات الإدارة لجميع المعاونين بنجاح.'
            if prev:
                msg = f'تم استعادة التحكم وتجميد أدوات المعاون ({prev.full_name}) بنجاح.'

            return JsonResponse({
                'ok': True,
                'action': 'revoke',
                'message': msg
            })

        else:
            return JsonResponse({'ok': False, 'error': 'إجراء غير صالح.'}, status=400)


# ── Topic Live Status Query API ──────────────────────────────────────────────
@login_required(login_url='/login/')
@require_GET
def api_topic_state(request, topic_pk):
    """
    Polling endpoint for members and projectors to get real-time state of a topic.
    Requires can_view_live_session, can_start_session_live, or can_view_projector.
    """
    user = request.user
    if not (user.is_super or user.can_view_live_session or user.can_start_session_live or user.can_view_projector):
        return JsonResponse({'ok': False, 'error': 'غير مصرح لك بالوصول لبيانات الانعقاد الحي.'}, status=403)

    topic = get_object_or_404(Topic, pk=topic_pk)
    state = topic.get_display_state()
    summary = topic.get_vote_summary()
    percentages = state.get_vote_percentages()
    user_vote = topic.get_user_vote(request.user)

    return JsonResponse({
        'ok': True,
        'topic_id': topic.pk,
        'title': topic.title,
        'display_status': state.display_status,
        'display_status_label': state.get_display_status_display(),
        'allocated_minutes': state.allocated_minutes,
        'remaining_seconds': state.get_remaining_seconds(),
        'is_voting_open': state.display_status == 'voting',
        'summary': summary,
        'percentages': percentages,
        'has_user_voted': user_vote is not None,
        'user_choice': user_vote.choice if user_vote else None,
        'user_choice_label': user_vote.get_choice_display() if user_vote else None,
    })


# ── Speech Queue APIs (SpeakRequest) ─────────────────────────────────────────
@login_required(login_url='/login/')
@require_POST
def api_speak_request_toggle(request, session_pk):
    """
    Council member requests the floor or cancels an existing pending request.
    Requires can_request_speak permission.
    """
    if not (request.user.is_super or request.user.can_request_speak):
        return JsonResponse({'ok': False, 'error': 'ليس لديك صلاحية لطلب الكلمة والمداخلة.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)

    # Check if user has an approved exit permit
    if ExitPermit.objects.filter(session=session, member=request.user, status='approved').exists():
        return JsonResponse({
            'ok': False,
            'error': 'تمت الموافقة على مغادرتك للجلسة مسبقاً، لا يمكنك طلب الكلمة.'
        }, status=403)

    user_seat = EntitySeat.objects.filter(
        Q(primary_rep=request.user) | Q(deputy_rep_1=request.user) | Q(deputy_rep_2=request.user),
        is_active=True
    ).first()

    pending_req = SpeakRequest.objects.filter(
        session=session, member=request.user, status='pending'
    ).first()

    if pending_req:
        pending_req.delete()
        return JsonResponse({
            'ok': True,
            'action': 'cancelled',
            'message': 'تم إلغاء طلب الكلمة بنجاح.'
        })

    # Active topic
    active_topic = session.get_live_active_topic()

    req = SpeakRequest.objects.create(
        session=session,
        topic=active_topic,
        member=request.user,
        seat=user_seat,
        status='pending'
    )

    return JsonResponse({
        'ok': True,
        'action': 'requested',
        'request_id': req.pk,
        'message': 'تم إدراج طلبك في طابور المداخلات بنجاح.'
    })


@login_required(login_url='/login/')
@require_POST
def api_speak_request_action(request, request_pk):
    """
    Council President manages speech queue:
    - allow (grant floor, record speech start offset)
    - complete (end speech, record speech end offset)
    - pass (pass turn)
    - reject (reject request)
    """
    sr = get_object_or_404(SpeakRequest.objects.select_related('session', 'member'), pk=request_pk)
    session = sr.session

    if not session.user_can_manage_live_controls(request.user):
        return JsonResponse({'ok': False, 'error': 'أدوات إدارة طابور الكلمة مجمدة حالياً بانتظار تمكين رئيس الجلسة.'}, status=403)

    if not (request.user.is_super or request.user.can_manage_speak_requests or session.user_can_manage_live_controls(request.user)):
        return JsonResponse({'ok': False, 'error': 'غير مصرح لك بإدارة طابور المداخلات.'}, status=403)

    recording = getattr(session, 'recording', None)

    try:
        data = json.loads(request.body) if request.body else request.POST
    except Exception:
        data = request.POST

    action = data.get('action')

    with transaction.atomic():
        if action == 'allow':
            # Complete any currently speaking request
            currently_speaking = SpeakRequest.objects.filter(session=session, status='speaking').first()
            if currently_speaking:
                currently_speaking.status = 'completed'
                currently_speaking.completed_at = timezone.now()
                if recording and recording.started_at:
                    elapsed = max(0, int((timezone.now() - recording.started_at).total_seconds()))
                    currently_speaking.speak_end_offset = elapsed
                currently_speaking.save()

            sr.status = 'speaking'
            sr.allowed_at = timezone.now()
            if recording and recording.started_at:
                elapsed = max(0, int((timezone.now() - recording.started_at).total_seconds()))
                sr.speak_start_offset = elapsed
            sr.save()
            msg = f'تم منح الكلمة للأخ / {sr.member.full_name}.'

        elif action == 'complete':
            sr.status = 'completed'
            sr.completed_at = timezone.now()
            if recording and recording.started_at:
                elapsed = max(0, int((timezone.now() - recording.started_at).total_seconds()))
                sr.speak_end_offset = elapsed
            sr.save()
            msg = f'تم إنهاء مداخلة الأخ / {sr.member.full_name}.'

        elif action == 'pass':
            sr.status = 'passed'
            sr.save()
            msg = 'تم تمرير الدور.'

        elif action == 'reject':
            sr.status = 'rejected'
            sr.save()
            msg = 'تم رفض الطلب.'

        else:
            return JsonResponse({'ok': False, 'error': 'إجراء غير معروف.'}, status=400)

    return JsonResponse({'ok': True, 'message': msg, 'status': sr.status})


@login_required(login_url='/login/')
@require_GET
def api_speak_queue(request, session_pk):
    """
    Comprehensive real-time polling endpoint returning:
    - speech queue & active speaker
    - live quorum status
    - all topics display states, timers, vote summaries, and decisions
    - pending exit permits & user's exit permit status
    """
    user = request.user
    if not (user.is_super or user.can_view_live_session or user.can_start_session_live or user.can_view_projector):
        return JsonResponse({'ok': False, 'error': 'غير مصرح لك بعرض بيانات الجلسة الحية.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)

    # Heartbeat presence tracking for operators/managers
    if user.is_authenticated and (user.is_super or user.can_start_session_live):
        LiveSessionPresence.objects.update_or_create(
            session=session, user=user,
            defaults={'last_seen': timezone.now(), 'is_active': True}
        )

    active_speaker = SpeakRequest.objects.filter(
        session=session, status='speaking'
    ).select_related('member', 'seat').first()

    pending = SpeakRequest.objects.filter(
        session=session, status='pending'
    ).select_related('member', 'seat', 'topic').order_by('requested_at')

    active_data = None
    if active_speaker:
        elapsed = 0
        if active_speaker.allowed_at:
            elapsed = int((timezone.now() - active_speaker.allowed_at).total_seconds())
        active_data = {
            'id': active_speaker.pk,
            'name': active_speaker.member.full_name,
            'seat': active_speaker.seat.name if active_speaker.seat else (active_speaker.member.department or 'عضو مجلس'),
            'allowed_at': active_speaker.allowed_at.strftime('%H:%M:%S') if active_speaker.allowed_at else '',
            'elapsed_seconds': elapsed,
            'speak_start_offset': active_speaker.speak_start_offset,
        }

    pending_list = []
    for p in pending:
        pending_list.append({
            'id': p.pk,
            'name': p.member.full_name,
            'seat': p.seat.name if p.seat else (p.member.department or 'عضو مجلس'),
            'topic_title': p.topic.title[:40] if p.topic else '',
            'requested_at': p.requested_at.strftime('%H:%M:%S'),
        })

    user_has_pending = SpeakRequest.objects.filter(
        session=session, member=request.user, status='pending'
    ).exists()
    user_is_speaking = bool(active_speaker and active_speaker.member_id == request.user.id)

    # Topics live state synchronization
    cat_order_map = {cat_key: idx for idx, (cat_key, _) in enumerate(TOPIC_CATEGORIES)}
    raw_topics = list(
        session.topics.select_related('display_state', 'decision')
        .prefetch_related('votes')
        .order_by('sub_order', 'order_number', 'id')
    )
    topics = sorted(raw_topics, key=lambda t: (cat_order_map.get(t.category, 99), t.sub_order, t.order_number, t.id))

    topics_state = {}
    active_topic_id = None
    completed_topics_count = 0

    for t in topics:
        st = getattr(t, 'display_state', None)
        if not st:
            st, _ = TopicDisplayState.objects.get_or_create(topic=t)
        has_dec = t.has_decision()
        dec_text = t.decision.decision_text if has_dec else ''
        if t.status in ('voted', 'closed') or st.display_status == 'closed' or has_dec:
            completed_topics_count += 1
        if st.display_status in ('voting', 'shown') and active_topic_id is None:
            active_topic_id = t.pk

        u_vote = t.get_user_vote(request.user)
        rem_secs = st.get_remaining_seconds() if st else 0
        topics_state[str(t.pk)] = {
            'id': t.pk,
            'category': t.category,
            'category_label': t.get_category_display(),
            'sub_order': t.sub_order,
            'ordinal_label': t.ordinal_label,
            'title': t.title,
            'background': t.background or '',
            'priorities': t.priorities or '',
            'presenting_entity': t.presenting_entity or '',
            'memo_number': t.memo_number or '',
            'memo_date': str(t.memo_date) if t.memo_date else '',
            'topic_status': t.status,
            'postponed_to': getattr(t, 'postponed_to', ''),
            'postpone_reason': getattr(t, 'postpone_reason', ''),
            'display_status': st.display_status,
            'display_status_label': st.get_display_status_display(),
            'allocated_minutes': st.allocated_minutes,
            'remaining_seconds': rem_secs,
            'timer_running': bool(st.timer_started_at and rem_secs > 0),
            'is_voting_open': st.display_status == 'voting',
            'summary': t.get_vote_summary(),
            'percentages': st.get_vote_percentages(),
            'has_decision': has_dec,
            'decision_text': dec_text,
            'has_user_voted': u_vote is not None,
            'user_choice': u_vote.choice if u_vote else None,
            'user_choice_label': u_vote.get_choice_display() if u_vote else None,
        }

    total_topics_count = len(topics)
    progress_pct = round((completed_topics_count / total_topics_count) * 100) if total_topics_count else 0

    # Quorum & Exit Permits
    quorum_info = session.get_quorum_info()
    pending_exits = [
        {
            'id': ep.pk,
            'member_name': ep.member.full_name,
            'seat_name': ep.seat.name if ep.seat else (ep.member.department or ''),
            'reason': ep.reason or '',
            'requested_at': ep.requested_at.strftime('%H:%M') if getattr(ep, 'requested_at', None) else '',
        }
        for ep in ExitPermit.objects.filter(session=session, status='pending').select_related('member', 'seat')
    ]
    user_ep = ExitPermit.objects.filter(session=session, member=request.user).first()

    # Online Managers List for Dynamic Cockpit Updates
    presence_cutoff = timezone.now() - timezone.timedelta(minutes=10)
    manager_presences = (
        LiveSessionPresence.objects.filter(session=session)
        .select_related('user')
        .order_by('-last_seen')
    )
    online_managers = []
    for p in manager_presences:
        if session.is_user_president(p.user):
            continue
        is_online = (p.last_seen >= presence_cutoff) and p.is_active
        online_managers.append({
            'id': p.user.pk,
            'name': p.user.full_name,
            'title': p.user.official_title or p.user.get_title_display(),
            'avatar_initials': getattr(p.user, 'avatar_initials', '') or p.user.full_name[:2],
            'is_online': is_online,
            'is_delegated': bool(session.live_controller_id == p.user.pk),
            'last_seen': p.last_seen.strftime('%H:%M:%S'),
        })

    return JsonResponse({
        'ok': True,
        'active_speaker': active_data,
        'pending_speakers': pending_list,
        'pending_count': len(pending_list),
        'user_has_pending': user_has_pending,
        'user_is_speaking': user_is_speaking,
        'quorum_info': quorum_info,
        'active_topic_id': active_topic_id,
        'completed_topics_count': completed_topics_count,
        'total_topics_count': total_topics_count,
        'progress_pct': progress_pct,
        'topics_state': topics_state,
        'is_suspended': getattr(session, 'is_suspended', False),
        'suspension_reason': getattr(session, 'suspension_reason', ''),
        'session_status': session.status,
        'pending_exit_permits': pending_exits,
        'user_exit_status': user_ep.status if user_ep else None,
        'user_exit_time': user_ep.exit_time.strftime('%H:%M') if (user_ep and user_ep.exit_time) else '',
        'active_controller_id': session.live_controller_id,
        'active_controller_name': session.live_controller.full_name if session.live_controller else None,
        'active_controller_title': (session.live_controller.official_title or session.live_controller.get_title_display()) if session.live_controller else None,
        'is_user_controller': session.user_can_manage_live_controls(request.user),
        'is_president': session.is_user_president(request.user),
        'chair_name': session.get_chair_display_name(),
        'online_managers': online_managers,
    })


# ── Audio Recording APIs (Continuous + Chunked Upload) ───────────────────────
@login_required(login_url='/login/')
@require_POST
def api_session_recording_action(request, session_pk):
    """
    President / Supervisor controls continuous session recording:
    start, pause, resume, stop.
    Requires can_control_recording permission.
    """
    session = get_object_or_404(CouncilSession, pk=session_pk)

    if not (request.user.is_super or session.user_can_manage_live_controls(request.user) or request.user.can_control_recording):
        return JsonResponse({'ok': False, 'error': 'أدوات التحكم بتسجيل الجلسة مجمدة حالياً بانتظار تمكين رئيس الجلسة.'}, status=403)

    recording, _ = SessionRecording.objects.get_or_create(session=session)

    try:
        data = json.loads(request.body) if request.body else request.POST
    except Exception:
        data = request.POST

    action = data.get('action')
    now = timezone.now()

    if action == 'start':
        # Reset old master audio file so new WebM stream starts with a clean header
        rec_dir = os.path.join(settings.MEDIA_ROOT, 'session_recordings', f'session_{session.pk}')
        master_path = os.path.join(rec_dir, 'session_master_audio.webm')
        if os.path.exists(master_path):
            try:
                os.remove(master_path)
            except OSError:
                pass
        recording.started_at = now
        recording.ended_at = None
        recording.paused_at = None
        recording.is_paused = False
        recording.chunk_count = 0
        recording.duration_seconds = 0
        recording.total_paused_seconds = 0
        recording.recorded_by = request.user
        recording.save()
        msg = 'تم بدء التسجيل الصوتي للجلسة بنجاح.'

    elif action == 'pause':
        if not recording.is_paused:
            recording.is_paused = True
            recording.paused_at = now
            recording.save()
        msg = 'تم إيقاف التسجيل مؤقتاً.'

    elif action == 'resume':
        if recording.is_paused and recording.paused_at:
            paused_duration = int((now - recording.paused_at).total_seconds())
            recording.total_paused_seconds += max(0, paused_duration)
            recording.is_paused = False
            recording.paused_at = None
            recording.save()
        msg = 'تم استئناف التسجيل الصوتي.'

    elif action == 'stop':
        recording.ended_at = now
        recording.is_paused = False
        if recording.started_at:
            raw_seconds = int((now - recording.started_at).total_seconds())
            recording.duration_seconds = max(0, raw_seconds - recording.total_paused_seconds)
        recording.save()
        msg = f'تم إيقاف وحفظ التسجيل الصوتي (المدة: {recording.get_duration_display()}).'

    else:
        return JsonResponse({'ok': False, 'error': 'إجراء غير معروف.'}, status=400)

    return JsonResponse({
        'ok': True,
        'message': msg,
        'is_recording': recording.started_at is not None and recording.ended_at is None,
        'is_paused': recording.is_paused,
        'duration_display': recording.get_duration_display(),
        'duration_seconds': recording.duration_seconds,
    })


@csrf_exempt
@login_required(login_url='/login/')
@require_POST
def api_session_recording_chunk(request, session_pk):
    """
    Chunked upload endpoint. Receives periodic audio chunks from client's MediaRecorder
    and appends them safely to disk. Requires can_control_recording.
    """
    if not (request.user.is_super or request.user.can_control_recording):
        return JsonResponse({'ok': False, 'error': 'غير مصرح.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)
    recording, _ = SessionRecording.objects.get_or_create(session=session)

    audio_file = request.FILES.get('audio_chunk')
    if not audio_file:
        return JsonResponse({'ok': False, 'error': 'لم يتم استلام ملف صوتي.'}, status=400)

    # Destination directory
    rec_dir = os.path.join(settings.MEDIA_ROOT, 'session_recordings', f'session_{session.pk}')
    os.makedirs(rec_dir, exist_ok=True)

    master_path = os.path.join(rec_dir, 'session_master_audio.webm')

    # Append chunk bytes to master file
    with open(master_path, 'ab') as f_out:
        for chunk in audio_file.chunks():
            f_out.write(chunk)

    recording.chunk_count += 1
    rel_path = os.path.relpath(master_path, settings.MEDIA_ROOT).replace('\\', '/')
    recording.audio_file.name = rel_path

    # Duration update if provided
    client_duration = request.POST.get('duration_seconds')
    if client_duration:
        try:
            recording.duration_seconds = int(float(client_duration))
        except ValueError:
            pass

    recording.save()

    return JsonResponse({
        'ok': True,
        'chunk_count': recording.chunk_count,
        'duration_seconds': recording.duration_seconds,
    })


# ── Exit Permits APIs ────────────────────────────────────────────────────────
@login_required(login_url='/login/')
@require_POST
def api_exit_permit_request(request, session_pk):
    """
    Member submits a request for formal leave / permanent exit from the session.
    Requires can_request_exit_permit permission.
    """
    if not (request.user.is_super or request.user.can_request_exit_permit):
        return JsonResponse({'ok': False, 'error': 'ليس لديك صلاحية لتقديم طلب استئذان ومغادرة.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)

    # Check existing permit
    existing = ExitPermit.objects.filter(session=session, member=request.user).first()
    if existing and existing.status == 'approved':
        return JsonResponse({'ok': False, 'error': 'تمت الموافقة على مغادرتك مسبقاً.'}, status=400)
    elif existing and existing.status == 'pending':
        return JsonResponse({'ok': False, 'error': 'طلبك قيد المراجعة لدى رئيس المجلس.'}, status=400)

    reason = request.POST.get('reason', '').strip()

    user_seat = EntitySeat.objects.filter(
        Q(primary_rep=request.user) | Q(deputy_rep_1=request.user) | Q(deputy_rep_2=request.user),
        is_active=True
    ).first()

    permit = ExitPermit.objects.create(
        session=session,
        member=request.user,
        seat=user_seat,
        reason=reason,
        status='pending'
    )

    return JsonResponse({
        'ok': True,
        'permit_id': permit.pk,
        'message': 'تم تقديم طلب الإذن بالمغادرة لرئيس المجلس بنجاح.'
    })


@login_required(login_url='/login/')
@require_POST
def api_exit_permit_action(request, permit_pk):
    """
    President reviews exit permit (approve/reject).
    Requires can_approve_exit_permit permission.
    """
    if not (request.user.is_super or request.user.can_approve_exit_permit):
        return JsonResponse({'ok': False, 'error': 'غير مصرح لك بالبت في أذونات المغادرة.'}, status=403)

    permit = get_object_or_404(ExitPermit.objects.select_related('session', 'member', 'seat'), pk=permit_pk)

    try:
        data = json.loads(request.body) if request.body else request.POST
    except Exception:
        data = request.POST

    action = data.get('action')

    with transaction.atomic():
        if action == 'approve':
            permit.status = 'approved'
            permit.reviewed_by = request.user
            permit.reviewed_at = timezone.now()
            permit.exit_time = timezone.now()
            permit.save()

            # Record departure in attendance note
            att = Attendance.objects.filter(session=permit.session, member=permit.member).first()
            if att:
                time_str = permit.exit_time.strftime('%H:%M')
                att.notes = f"{att.notes} | غادر القاعة بإذن رسمي الساعة {time_str}".strip(' |')
                att.save(update_fields=['notes'])

            msg = f'تمت الموافقة على مغادرة الأخ / {permit.member.full_name}، وتوثيق وقت الخروج.'

        elif action == 'reject':
            permit.status = 'rejected'
            permit.reviewed_by = request.user
            permit.reviewed_at = timezone.now()
            permit.save()
            msg = f'تم رفض طلب المغادرة للأخ / {permit.member.full_name}، ويستمر بالجلسة.'

        else:
            return JsonResponse({'ok': False, 'error': 'إجراء غير معروف.'}, status=400)

    # Return updated quorum info
    quorum_info = permit.session.get_quorum_info()

    return JsonResponse({
        'ok': True,
        'message': msg,
        'status': permit.status,
        'quorum_info': quorum_info,
    })


# ── Quorum Real-time Status API ──────────────────────────────────────────────
@login_required(login_url='/login/')
@require_GET
def api_session_quorum(request, session_pk):
    """
    Polling endpoint returning live legal quorum information.
    """
    user = request.user
    if not (user.is_super or user.can_view_live_session or user.can_start_session_live or user.can_view_projector):
        return JsonResponse({'ok': False, 'error': 'غير مصرح لك بعرض نصاب الجلسة الحية.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)
    info = session.get_quorum_info()
    return JsonResponse({'ok': True, 'quorum': info})


@login_required(login_url='/login/')
@require_GET
def api_session_active_topic(request, session_pk):
    """
    Lightweight polling endpoint to detect if a topic is actively being presented
    or voted on in this live session, enabling auto-redirection of members.
    """
    user = request.user
    if not (user.is_super or user.can_view_live_session or user.can_start_session_live or user.can_view_topics):
        return JsonResponse({'ok': False, 'error': 'غير مصرح.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)
    active_state = TopicDisplayState.objects.filter(
        topic__session_id=session.pk,
        display_status__in=['shown', 'voting']
    ).select_related('topic').first()

    if active_state:
        return JsonResponse({
            'ok': True,
            'has_active': True,
            'topic_id': active_state.topic.pk,
            'topic_title': active_state.topic.title,
            'display_status': active_state.display_status,
            'live_url': f'/sessions/{session.pk}/live/'
        })
    return JsonResponse({'ok': True, 'has_active': False})


@login_required(login_url='/login/')
@require_GET
def api_topic_quick_view(request, topic_pk):
    """
    Returns full details of any topic including description, proposals,
    dynamic tables, and attachments for quick side-drawer inspection
    inside the live session cockpit without leaving the session.
    """
    user = request.user
    topic = get_object_or_404(Topic, pk=topic_pk)
    if not topic.session.can_be_seen_by(user):
        return JsonResponse({'ok': False, 'error': 'غير مصرح.'}, status=403)

    tables_data = []
    for tbl in topic.tables.all():
        tables_data.append({
            'id': tbl.id,
            'title': tbl.title or tbl.get_table_type_display(),
            'headers': tbl.headers or [],
            'rows': tbl.rows_data or [],
            'total_row': tbl.get_formatted_total_row() or [],
        })

    attachments_data = []
    for att in topic.attachments.all():
        attachments_data.append({
            'id': att.id,
            'name': att.file_name or (att.file.name.split('/')[-1] if att.file else 'مرفق'),
            'url': att.file.url if att.file else '#',
            'type': att.file_type or '',
        })

    recordings_data = []
    for rec in topic.recordings.all():
        recordings_data.append({
            'id': rec.id,
            'label': rec.label or 'تسجيل نقاش الموضوع',
            'url': rec.audio_file.url if rec.audio_file else '',
            'duration': rec.get_duration_display(),
            'recorded_at': rec.recorded_at.strftime('%Y-%m-%d %H:%M') if rec.recorded_at else '',
        })

    has_dec = topic.has_decision()
    dec_text = topic.decision.decision_text if has_dec else ''

    display_status = 'hidden'
    if hasattr(topic, 'display_state'):
        display_status = topic.display_state.display_status
    else:
        st = TopicDisplayState.objects.filter(topic=topic).first()
        if st:
            display_status = st.display_status

    return JsonResponse({
        'ok': True,
        'id': topic.pk,
        'title': topic.title,
        'ordinal_label': topic.ordinal_label,
        'category': topic.category,
        'category_label': topic.get_category_display(),
        'presenting_entity': topic.presenting_entity or '',
        'legal_basis': topic.background or '',
        'description': '',
        'priorities': topic.priorities or '',
        'decision_text': dec_text,
        'tables': tables_data,
        'attachments': attachments_data,
        'recordings': recordings_data,
        'display_status': display_status,
        'status': topic.status,
        'status_display': topic.get_clear_status_display(),
    })
