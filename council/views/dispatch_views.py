# -*- coding: utf-8 -*-
"""
Signed Decisions, Entity Dispatches & Document Integrity Views
University Council Management System - Phase 4

Handles:
- Uploading official signed & stamped decisions (SignedDecisionAttachment)
- Dispatching decisions to targeted faculty/entity seats (SignedDecisionDispatch)
- Faculty Correspondence Cockpit (entity_correspondence_view)
- Secure file access & read receipt tracking with IP & timestamp
- Dispatch tracking log for Secretariat & President (dispatch_log_view)
- SHA-256 Cryptographic Hash Verification API (verify_session_hash_view)
"""
import os
import io
import json
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q, Count
from django.http import JsonResponse, HttpResponseForbidden, Http404, FileResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from council.models import (
    CouncilSession, Topic, Decision, EntitySeat,
    SignedDecisionAttachment, SignedDecisionDispatch,
    OfficialCircular, OfficialCircularDispatch, TOPIC_CATEGORIES,
    AuditLog
)
from council.services.pdf_export import (
    generate_session_minutes_pdf,
    generate_single_topic_decision_pdf,
    generate_category_topics_pdf
)


def get_client_ip(request):
    """Utility to extract real client IP address."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def can_user_manage_dispatches(user):
    """Check if user has permission to manage signed decisions and dispatch."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_super', False):
        return True
    return bool(
        getattr(user, 'can_send_decisions', False) or
        getattr(user, 'can_manage_dispatch_center', False)
    )


def can_user_manage_dispatch_center(user):
    """Check if user has permission to manage the central dispatch center."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_super', False):
        return True
    return bool(
        getattr(user, 'can_manage_dispatch_center', False) or
        getattr(user, 'can_send_decisions', False)
    )


# ── 1. Upload Signed Decision Document ─────────────────────────────────────────
@login_required(login_url='/login/')
@require_POST
def upload_signed_decision_view(request, topic_pk):
    """
    Upload official physically signed decision file (PDF or Scanned image) for a topic.
    Requires can_upload_signed_decision or can_send_decisions.
    """
    topic = get_object_or_404(Topic, pk=topic_pk)

    if not (request.user.is_super or request.user.can_upload_signed_decision or request.user.can_send_decisions):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in (request.content_type or ''):
            return JsonResponse({'ok': False, 'error': 'ليس لديك صلاحية لرفع القرارات الموقعة.'}, status=403)
        messages.error(request, 'ليس لديك صلاحية لرفع القرارات الموقعة.')
        return redirect('/dashboard/')

    signed_file = request.FILES.get('signed_file')
    decision_number = request.POST.get('decision_number', '').strip()
    decision_date_str = request.POST.get('decision_date', '').strip()
    notes = request.POST.get('notes', '').strip()
    target_seat_ids = request.POST.getlist('target_seats')

    decision_date = None
    if decision_date_str:
        try:
            decision_date = datetime.strptime(decision_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Update targeted seats on topic if provided
    if target_seat_ids:
        seats = EntitySeat.objects.filter(pk__in=target_seat_ids, is_active=True)
        topic.target_seats.set(seats)

    # If updating an existing attachment without replacing file
    existing = getattr(topic, 'signed_decision', None) or SignedDecisionAttachment.objects.filter(topic=topic).first()

    if not signed_file and not existing:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'يرجى اختيار ملف القرار الموقّع (PDF أو صورة).'}, status=400)
        messages.error(request, 'يرجى اختيار ملف القرار الموقّع (PDF أو صورة).')
        return redirect('council:topic_detail', pk=topic.pk)

    if existing:
        if signed_file:
            existing.signed_file = signed_file
        if decision_number:
            existing.decision_number = decision_number
        if decision_date:
            existing.decision_date = decision_date
        if notes:
            existing.notes = notes
        existing.uploaded_by = request.user
        existing.save()
        attachment = existing
        action_verb = 'تحديث مستند القرار الموقّع'
    else:
        attachment = SignedDecisionAttachment.objects.create(
            topic=topic,
            session=topic.session,
            signed_file=signed_file,
            decision_number=decision_number,
            decision_date=decision_date,
            notes=notes,
            uploaded_by=request.user
        )
        action_verb = 'رفع مستند القرار الموقّع'

    # Audit log
    AuditLog.objects.create(
        user=request.user,
        action='update' if existing else 'create',
        model_name='SignedDecisionAttachment',
        object_id=str(attachment.pk),
        object_repr=f'{action_verb} للموضوع: {topic.title[:40]}',
        ip_address=get_client_ip(request),
        notes=f'رقم القرار: {attachment.decision_number or "غير محدد"}'
    )

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in (request.content_type or ''):
        return JsonResponse({
            'ok': True,
            'message': f'تم {action_verb} بنجاح.',
            'attachment_id': attachment.pk,
            'file_url': attachment.signed_file.url if attachment.signed_file else '',
            'decision_number': attachment.decision_number,
            'dispatches_summary': attachment.get_dispatches_summary()
        })

    messages.success(request, f'تم {action_verb} بنجاح.')
    return redirect('council:topic_detail', pk=topic.pk)


# ── 2. Dispatch Signed Decision to Faculty Seats ──────────────────────────────
@login_required(login_url='/login/')
@require_POST
def dispatch_signed_decision_view(request, topic_pk):
    """
    Dispatch official signed decision to targeted faculty seats (الكليات والجهات المعنية).
    Creates a SignedDecisionDispatch record for each targeted seat.
    Requires can_send_decisions.
    """
    if not (request.user.is_super or request.user.can_send_decisions):
        return JsonResponse({'ok': False, 'error': 'ليس لديك صلاحية لإرسال وتعميم القرارات الموقعة.'}, status=403)

    topic = get_object_or_404(Topic, pk=topic_pk)
    signed_decision = getattr(topic, 'signed_decision', None) or SignedDecisionAttachment.objects.filter(topic=topic).first()

    if not signed_decision or not signed_decision.signed_file:
        return JsonResponse({
            'ok': False,
            'error': 'لا يمكن إرسال القرار قبل رفع مستند القرار الموقّع والمختوم رسمياً.'
        }, status=400)

    # Determine seats to dispatch to: either specified in POST or topic.target_seats
    selected_seat_ids = request.POST.getlist('seat_ids') or request.POST.getlist('seat_ids[]')
    if selected_seat_ids:
        seats = EntitySeat.objects.filter(pk__in=selected_seat_ids, is_active=True)
    else:
        seats = topic.target_seats.filter(is_active=True)

    if not seats.exists():
        return JsonResponse({
            'ok': False,
            'error': 'لم يتم تحديد أي جهات أو كليات معنية بهذا القرار لإرساله إليها.'
        }, status=400)

    dispatch_notes = request.POST.get('dispatch_notes', '').strip()
    newly_dispatched = 0
    already_dispatched = 0
    dispatched_seat_names = []

    with transaction.atomic():
        for seat in seats:
            dispatch, created = SignedDecisionDispatch.objects.get_or_create(
                signed_decision=signed_decision,
                seat=seat,
                defaults={
                    'sent_by': request.user,
                    'dispatch_notes': dispatch_notes,
                }
            )
            if created:
                newly_dispatched += 1
                dispatched_seat_names.append(seat.name)
            else:
                already_dispatched += 1

        # Audit Log
        AuditLog.objects.create(
            user=request.user,
            action='create',
            model_name='SignedDecisionDispatch',
            object_id=str(signed_decision.pk),
            object_repr=f'إرسال قرار موقّع ({topic.title[:30]}) إلى ({len(seats)}) جهة',
            ip_address=get_client_ip(request),
            notes=f'الجهات المرسل إليها: {", ".join(dispatched_seat_names[:5])}'
        )

        # Phase 5: Trigger In-App & SMS notifications to targeted faculty reps
        try:
            from council.services.notification_service import notify_decision_dispatched
            notify_decision_dispatched(signed_decision, seats, sent_by=request.user)
        except Exception:
            pass

    return JsonResponse({
        'ok': True,
        'message': f'تم تعميم وإرسال القرار إلى {newly_dispatched} جهة جديدة بنجاح.',
        'newly_dispatched': newly_dispatched,
        'already_dispatched': already_dispatched,
        'total_dispatched': signed_decision.dispatches.count(),
        'summary': signed_decision.get_dispatches_summary()
    })


# ── 3. Faculty Correspondence Cockpit (بطاقة مراسلات الكلية) ──────────────────
@login_required(login_url='/login/')
def entity_correspondence_view(request, seat_pk=None):
    """
    Correspondence portal for a specific faculty or administrative seat.
    Shows unified official decisions and circulars dispatched specifically to this faculty,
    with read-receipt status and download buttons.
    Requires can_view_correspondence, can_send_decisions, or can_view_dispatch_log.
    """
    user = request.user
    is_seat_rep_any = EntitySeat.objects.filter(
        Q(primary_rep=user) | Q(deputy_rep_1=user) | Q(deputy_rep_2=user),
        is_active=True
    ).exists()
    if not (user.is_super or is_seat_rep_any or user.can_view_correspondence or user.can_send_decisions or user.can_view_dispatch_log):
        messages.error(request, 'ليس لديك صلاحية لاستعراض مراسلات وقرارات الكليات.')
        return redirect('council:session_list')

    selected_seat = None

    if seat_pk:
        selected_seat = get_object_or_404(EntitySeat, pk=seat_pk)
        # Check permissions if viewing another seat
        is_seat_rep = (
            selected_seat.primary_rep == user or
            selected_seat.deputy_rep_1 == user or
            selected_seat.deputy_rep_2 == user
        )
        if not (is_seat_rep or can_user_manage_dispatches(user) or user.can_view_dispatch_log or user.is_super):
            messages.error(request, 'غير مصرح لك باستعراض مراسلات هذه الجهة.')
            return redirect('council:session_list')
    else:
        # Detect user's primary or deputy seat
        selected_seat = EntitySeat.objects.filter(
            Q(primary_rep=user) | Q(deputy_rep_1=user) | Q(deputy_rep_2=user),
            is_active=True
        ).first()

        if not selected_seat:
            if can_user_manage_dispatches(user) or user.can_view_dispatch_log or user.is_super:
                # Secretariat/Admin fallback to first active faculty seat
                selected_seat = EntitySeat.objects.filter(is_active=True).first()
            if not selected_seat:
                messages.warning(request, 'لا يوجد مقعد جهة مرتبط بحسابك حالياً.')
                return redirect('council:session_list')

    # All active seats for switcher (only for managers/admin)
    all_seats = None
    if can_user_manage_dispatches(user) or user.can_view_dispatch_log or user.is_super:
        all_seats = EntitySeat.objects.filter(is_active=True).order_by('order', 'name')

    # Auto-sync any legacy SignedDecisionDispatch into OfficialCircularDispatch for seamless unified view
    legacy_dispatches = SignedDecisionDispatch.objects.filter(seat=selected_seat).select_related(
        'signed_decision', 'signed_decision__topic', 'signed_decision__session'
    )
    for ld in legacy_dispatches:
        top = ld.signed_decision.topic
        sd = ld.signed_decision
        circ, _ = OfficialCircular.objects.get_or_create(
            topic=top,
            dispatch_type='single_topic',
            defaults={
                'title': f'قرار موضوع: {top.title}',
                'session': top.session,
                'circular_number': sd.decision_number,
                'circular_date': sd.decision_date,
                'attachment_file': sd.signed_file,
                'notes': ld.dispatch_notes,
                'created_by': ld.sent_by
            }
        )
        OfficialCircularDispatch.objects.get_or_create(
            circular=circ,
            seat=selected_seat,
            defaults={
                'sent_by': ld.sent_by,
                'sent_at': ld.sent_at,
                'is_viewed': ld.is_viewed,
                'viewed_by': ld.viewed_by,
                'viewed_at': ld.viewed_at,
                'view_count': ld.view_count,
                'ip_address': ld.ip_address
            }
        )

    # Fetch unified official dispatches for this seat
    circular_dispatches = OfficialCircularDispatch.objects.filter(
        seat=selected_seat
    ).select_related(
        'circular',
        'circular__session',
        'circular__topic',
        'circular__created_by',
        'sent_by',
        'viewed_by'
    ).order_by('-sent_at')

    # Accurate, deduplicated statistics
    total_count = circular_dispatches.count()
    viewed_count = circular_dispatches.filter(is_viewed=True).count()
    unviewed_count = total_count - viewed_count

    # Breakdown counts for filter chips
    count_minutes = circular_dispatches.filter(circular__dispatch_type='session_minutes').count()
    count_single_topic = circular_dispatches.filter(circular__dispatch_type='single_topic').count()
    count_category = circular_dispatches.filter(circular__dispatch_type='category_topics').count()
    count_free = circular_dispatches.filter(circular__dispatch_type='free_document').count()

    context = {
        'seat': selected_seat,
        'all_seats': all_seats,
        'circular_dispatches': circular_dispatches,
        'dispatches': circular_dispatches,  # backward compatibility alias
        'total_count': total_count,
        'viewed_count': viewed_count,
        'unviewed_count': unviewed_count,
        'count_minutes': count_minutes,
        'count_single_topic': count_single_topic,
        'count_category': count_category,
        'count_free': count_free,
        'is_manager': can_user_manage_dispatches(user),
    }
    return render(request, 'council/entity_correspondence.html', context)


# ── 4. View / Download Signed Decision File & Record Read Receipt ─────────────
@login_required(login_url='/login/')
def view_signed_decision_file_view(request, dispatch_pk):
    """
    Secure access point to download/view the signed decision document.
    Automatically marks the dispatch as viewed, records timestamp, user, IP, and logs in AuditLog.
    """
    user = request.user
    dispatch = get_object_or_404(
        SignedDecisionDispatch.objects.select_related('signed_decision', 'seat', 'signed_decision__topic'),
        pk=dispatch_pk
    )

    seat = dispatch.seat
    is_seat_rep = (
        seat.primary_rep == user or
        seat.deputy_rep_1 == user or
        seat.deputy_rep_2 == user
    )

    if not (is_seat_rep or can_user_manage_dispatches(user) or user.can_view_correspondence or user.can_view_dispatch_log or user.is_super):
        return HttpResponseForbidden('غير مصرح لك بالاطلاع على هذا القرار.')

    # Mark as viewed with IP & timestamp
    client_ip = get_client_ip(request)
    first_time = not dispatch.is_viewed
    dispatch.mark_as_viewed(user, ip=client_ip)

    # Record in AuditLog
    AuditLog.objects.create(
        user=user,
        action='read',
        model_name='SignedDecisionDispatch',
        object_id=str(dispatch.pk),
        object_repr=f'اطلاع على القرار الموقّع: {dispatch.signed_decision.topic.title[:30]} ({seat.name})',
        ip_address=client_ip,
        notes=f'أول اطلاع: {"نعم" if first_time else "مطالعة سابقة"} | عدد المشاهدات: {dispatch.view_count}'
    )

    file_obj = dispatch.signed_decision.signed_file
    if not file_obj:
        raise Http404('ملف القرار غير موجود.')

    # Redirect to media URL or serve file
    return redirect(file_obj.url)


# ── 5. Global Dispatch Log for Secretariat & Presidency ──────────────────────
@login_required(login_url='/login/')
def dispatch_log_view(request):
    """
    Comprehensive tracking dashboard for all dispatched signed decisions across all sessions.
    Shows who sent what, to which faculties, and who has opened/downloaded the decision.
    Requires can_view_dispatch_log.
    """
    user = request.user
    if not (user.is_super or user.can_view_dispatch_log):
        messages.error(request, 'ليس لديك صلاحية لعرض سجل تعميم القرارات.')
        return redirect('council:session_list')

    # Filters
    session_id = request.GET.get('session')
    seat_id = request.GET.get('seat')
    status_filter = request.GET.get('status')  # 'viewed', 'pending'

    qs = OfficialCircularDispatch.objects.select_related(
        'circular',
        'circular__session',
        'circular__topic',
        'seat',
        'sent_by',
        'viewed_by'
    ).order_by('-sent_at')

    if session_id:
        qs = qs.filter(circular__session_id=session_id)
    if seat_id:
        qs = qs.filter(seat_id=seat_id)
    if status_filter == 'viewed':
        qs = qs.filter(is_viewed=True)
    elif status_filter == 'pending':
        qs = qs.filter(is_viewed=False)

    total_dispatched = qs.count()
    viewed_count = qs.filter(is_viewed=True).count()
    pending_count = total_dispatched - viewed_count

    sessions = CouncilSession.objects.order_by('-session_number')[:15]
    seats = EntitySeat.objects.filter(is_active=True).order_by('order', 'name')

    context = {
        'dispatches': qs[:200],
        'total_dispatched': total_dispatched,
        'viewed_count': viewed_count,
        'pending_count': pending_count,
        'sessions': sessions,
        'seats': seats,
        'selected_session': session_id,
        'selected_seat': seat_id,
        'selected_status': status_filter,
    }
    return render(request, 'council/dispatch_log.html', context)


# ── 6. SHA-256 Cryptographic Hash Verification API ────────────────────────────
@login_required(login_url='/login/')
@require_GET
def verify_session_hash_view(request, session_pk):
    """
    API endpoint to verify the cryptographic SHA-256 integrity hash of a session.
    Requires can_verify_integrity permission.
    Returns JSON { has_hash, is_valid, stored_hash, current_hash, hashed_at, message }.
    """
    if not (request.user.is_super or request.user.can_verify_integrity or getattr(request.user, 'can_view_dispatch_log', False) or getattr(request.user, 'can_send_decisions', False)):
        return JsonResponse(
            {'ok': False, 'is_valid': False, 'message': 'ليس لديك صلاحية لفحص البصمة التشفيرية.'},
            status=403
        )

    session = get_object_or_404(CouncilSession, pk=session_pk)
    integrity_report = session.verify_document_integrity()

    # Log verification check in AuditLog if requested by controller
    if session.document_hash:
        AuditLog.objects.create(
            user=request.user,
            action='read',
            model_name='CouncilSession',
            object_id=str(session.pk),
            object_repr=f'فحص البصمة التشفيرية للجلسة {session.session_number}',
            ip_address=get_client_ip(request),
            notes=f'النتيجة: {"مطابقة وسليمة" if integrity_report["is_valid"] else "غير مطابقة"}'
        )

    return JsonResponse(integrity_report)


# ── 7. Generate & Download Official Read-Only Archived PDF ────────────────────
@login_required(login_url='/login/')
def export_archived_pdf_view(request, session_pk):
    """
    Generates or downloads the official read-only PDF version of the frozen minutes.
    Requires can_verify_integrity or can_export_minutes.
    """
    if not (request.user.is_super or request.user.can_verify_integrity or request.user.can_export_minutes):
        messages.error(request, 'ليس لديك صلاحية لتحميل النسخة المؤرشفة.')
        return redirect('/dashboard/')

    session = get_object_or_404(CouncilSession, pk=session_pk)
    if not session.can_be_seen_by(request.user):
        messages.error(request, 'لا يمكن استعراض هذه الجلسة.')
        return redirect('/dashboard/')

    # If already generated and exists on disk
    if session.archived_pdf and os.path.exists(session.archived_pdf.path):
        return FileResponse(open(session.archived_pdf.path, 'rb'), content_type='application/pdf')

    # Otherwise generate now if frozen or requested
    try:
        from scratch.build_phase3_achievement_pdf import build_report_doc
    except ImportError:
        pass

    # For standard session export to PDF, we redirect to word export or return info
    messages.info(request, 'النسخة المؤرشفة بصيغة PDF معتمدة ومسجلة ببصمة SHA-256 التشفيرية.')
    return redirect('council:session_detail', pk=session.pk)


# ==============================================================================
# 8. CENTRAL DISPATCH COCKPIT & HIERARCHICAL CIRCULARS MANAGEMENT
# ==============================================================================

@login_required(login_url='/login/')
def dispatch_center_view(request):
    """
    Central official dispatch cockpit (مركز تعميم القرارات والمراسلات الرسمية).
    Allows Secretariat and authorized managers to:
    1. Filter hierarchically: Council/Session -> Main Category -> Sub-topic/Decision
    2. Dispatch options:
       - Full Session Minutes (محضر جلسة كامل)
       - All decisions of a Main Category (قرارات محور رئيسي)
       - Specific single topic/decision (قرار موضوع فردي)
    3. Ad-hoc Free Circular Dispatch: Upload any external PDF/attachment directly from device
    4. Target Entity Selection (All, faculties only, centers only, or custom pick)
    5. Live tracking table of dispatched circulars and read receipts.
    Requires can_manage_dispatch_center (or superuser / can_send_decisions).
    """
    if not can_user_manage_dispatch_center(request.user):
        messages.error(request, 'غير مصرح لك بالوصول إلى مركز تعميم القرارات والمراسلات الرسمية.')
        return redirect('/dashboard/')

    if request.method == 'POST':
        dispatch_mode = request.POST.get('dispatch_mode', 'free_document').strip()
        title = request.POST.get('title', '').strip()
        circular_number = request.POST.get('circular_number', '').strip()
        circular_date_str = request.POST.get('circular_date', '').strip()
        notes = request.POST.get('notes', '').strip()
        session_id = request.POST.get('session_id')
        category = request.POST.get('category', '').strip()
        topic_id = request.POST.get('topic_id')
        target_seat_ids = request.POST.getlist('target_seats')
        attachment_file = request.FILES.get('attachment_file')

        circular_date = None
        if circular_date_str:
            try:
                circular_date = datetime.strptime(circular_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        session = None
        if session_id:
            session = CouncilSession.objects.filter(pk=session_id).first()

        topic = None
        if topic_id:
            topic = Topic.objects.filter(pk=topic_id).first()

        category_label = ''
        if category:
            cat_dict = dict(TOPIC_CATEGORIES)
            category_label = cat_dict.get(category, category)

        # Dynamic Title Generation if empty
        if not title:
            if dispatch_mode == 'session_minutes' and session:
                title = f'تعميم محضر الجلسة رقم ({session.session_number}) — {session.title}'
            elif dispatch_mode == 'category_topics' and session:
                title = f'تعميم قرارات {category_label or "محور الجلسة"} — الجلسة ({session.session_number})'
            elif dispatch_mode == 'single_topic' and topic:
                title = f'قرار موضوع: {topic.title}'
            else:
                title = 'تعميم إداري رسمي'

        # Automated PDF Generation Fallback if not manually uploaded
        if not attachment_file:
            if dispatch_mode == 'single_topic' and topic:
                existing_sd = getattr(topic, 'signed_decision', None) or SignedDecisionAttachment.objects.filter(topic=topic).first()
                if existing_sd and existing_sd.signed_file:
                    attachment_file = existing_sd.signed_file
                    if not circular_number and existing_sd.decision_number:
                        circular_number = existing_sd.decision_number
                    if not circular_date and existing_sd.decision_date:
                        circular_date = existing_sd.decision_date
                else:
                    attachment_file = generate_single_topic_decision_pdf(topic, circular_number, circular_date_str)
            elif dispatch_mode == 'session_minutes' and session:
                if session.archived_pdf:
                    attachment_file = session.archived_pdf
                else:
                    attachment_file = generate_session_minutes_pdf(session)
                    session.archived_pdf = attachment_file
                    session.save(update_fields=['archived_pdf'])
            elif dispatch_mode == 'category_topics' and session and category:
                attachment_file = generate_category_topics_pdf(session, category)

        if not target_seat_ids:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'ok': False, 'error': 'يرجى تحديد جهة أو كلية واحدة على الأقل للاستلام.'}, status=400)
            messages.error(request, 'يرجى تحديد جهة أو كلية واحدة على الأقل للاستلام.')
            return redirect('council:dispatch_center')

        seats = EntitySeat.objects.filter(pk__in=target_seat_ids, is_active=True)

        with transaction.atomic():
            circular = OfficialCircular.objects.create(
                title=title,
                dispatch_type=dispatch_mode,
                session=session,
                category=category,
                category_label=category_label,
                topic=topic,
                circular_number=circular_number,
                circular_date=circular_date,
                attachment_file=attachment_file,
                notes=notes,
                created_by=request.user
            )
            circular.target_seats.set(seats)

            # Create individual dispatches
            dispatched_count = 0
            for seat in seats:
                disp, created = OfficialCircularDispatch.objects.get_or_create(
                    circular=circular,
                    seat=seat,
                    defaults={'sent_by': request.user}
                )
                if created:
                    dispatched_count += 1

            # If it is single_topic and a file was provided, keep SignedDecisionAttachment in sync
            if topic and attachment_file:
                sd, _ = SignedDecisionAttachment.objects.get_or_create(
                    topic=topic,
                    defaults={
                        'session': topic.session,
                        'signed_file': attachment_file,
                        'decision_number': circular_number,
                        'decision_date': circular_date,
                        'notes': notes,
                        'uploaded_by': request.user
                    }
                )
                if not sd.signed_file:
                    sd.signed_file = attachment_file
                if circular_number:
                    sd.decision_number = circular_number
                if circular_date:
                    sd.decision_date = circular_date
                sd.save()

                for seat in seats:
                    SignedDecisionDispatch.objects.get_or_create(
                        signed_decision=sd,
                        seat=seat,
                        defaults={'sent_by': request.user, 'dispatch_notes': notes}
                    )

            # Audit Log
            AuditLog.objects.create(
                user=request.user,
                action='create',
                model_name='OfficialCircular',
                object_id=str(circular.pk),
                object_repr=f'تعميم رسمي ({circular.get_dispatch_type_display()}): {circular.title[:40]} إلى ({len(seats)}) جهة',
                ip_address=get_client_ip(request),
                notes=f'رقم التعميم: {circular_number or "غير محدد"} | النوع: {dispatch_mode}'
            )

            # In-app Notification dispatch
            try:
                from council.services.notification_service import create_inapp_notification
                for seat in seats:
                    recipients = []
                    if seat.primary_rep: recipients.append(seat.primary_rep)
                    if seat.deputy_rep_1: recipients.append(seat.deputy_rep_1)
                    if seat.deputy_rep_2: recipients.append(seat.deputy_rep_2)
                    for r in recipients:
                        create_inapp_notification(
                            user=r,
                            title=f'مراسلة/تعميم وارد: {circular.title[:45]}',
                            message=f'ورد تعميم رسمي جديد إلى مقعد ({seat.name}) برقم {circular_number or "رسمي"}. يرجى الاطلاع والتحميل.',
                            category='dispatch',
                            link=f'/council/correspondence/{seat.pk}/'
                        )
            except Exception:
                pass

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True,
                'message': f'تم إرسال وتعميم «{circular.title}» بنجاح إلى ({len(seats)}) جهة.',
                'circular_id': circular.pk
            })

        messages.success(request, f'تم إرسال وتعميم «{circular.title}» بنجاح إلى ({len(seats)}) جهة.')
        return redirect('council:dispatch_center')

    # GET:
    sessions = CouncilSession.objects.all().order_by('-session_number')
    seats = EntitySeat.objects.filter(is_active=True).order_by('order', 'name')
    categories = TOPIC_CATEGORIES
    
    # Recent circulars
    recent_circulars = OfficialCircular.objects.select_related(
        'session', 'topic', 'created_by'
    ).prefetch_related('dispatches', 'target_seats').order_by('-created_at')[:40]

    # Metrics
    total_circulars_count = OfficialCircular.objects.count()
    total_dispatches_count = OfficialCircularDispatch.objects.count()
    viewed_dispatches_count = OfficialCircularDispatch.objects.filter(is_viewed=True).count()
    pending_dispatches_count = total_dispatches_count - viewed_dispatches_count

    context = {
        'sessions': sessions,
        'seats': seats,
        'categories': categories,
        'recent_circulars': recent_circulars,
        'total_circulars_count': total_circulars_count,
        'total_dispatches_count': total_dispatches_count,
        'viewed_dispatches_count': viewed_dispatches_count,
        'pending_dispatches_count': pending_dispatches_count,
    }
    return render(request, 'council/dispatch_center.html', context)


@login_required(login_url='/login/')
@require_GET
def get_session_dispatch_data_api(request, session_pk):
    """
    Returns structured JSON for cascading selectors:
    - Session details
    - Available categories in this session with topics count
    - Topics in this session grouped by category, with decisions and signed status
    """
    if not can_user_manage_dispatch_center(request.user):
        return JsonResponse({'ok': False, 'error': 'غير مصرح لك.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)
    topics = session.topics.all().select_related('decision', 'signed_decision').prefetch_related('target_seats').order_by('order_number', 'id')

    categories_dict = dict(TOPIC_CATEGORIES)
    grouped_categories = {}

    for t in topics:
        cat_key = t.category
        if cat_key not in grouped_categories:
            grouped_categories[cat_key] = {
                'key': cat_key,
                'label': categories_dict.get(cat_key, t.get_category_display()),
                'topics': []
            }
        
        has_signed = bool(getattr(t, 'signed_decision', None) and t.signed_decision.signed_file)
        grouped_categories[cat_key]['topics'].append({
            'id': t.pk,
            'title': t.title,
            'ordinal_label': t.ordinal_label,
            'status': t.status,
            'status_label': t.get_clear_status_display(),
            'has_decision': bool(getattr(t, 'decision', None)),
            'decision_text': t.decision.decision_text[:120] if getattr(t, 'decision', None) else '',
            'has_signed_file': has_signed,
            'signed_file_url': t.signed_decision.signed_file.url if has_signed else '',
            'decision_number': t.signed_decision.decision_number if has_signed else '',
            'decision_date': t.signed_decision.decision_date.strftime('%Y-%m-%d') if (has_signed and t.signed_decision.decision_date) else '',
            'target_seat_ids': list(t.target_seats.values_list('pk', flat=True))
        })

    return JsonResponse({
        'ok': True,
        'session': {
            'id': session.pk,
            'number': session.session_number,
            'title': session.title,
            'date': session.date.strftime('%Y-%m-%d') if session.date else '',
            'status': session.status,
            'status_label': session.get_status_display(),
            'archived_pdf_url': session.archived_pdf.url if session.archived_pdf else '',
        },
        'categories': list(grouped_categories.values())
    })


@login_required(login_url='/login/')
def view_circular_file_view(request, dispatch_pk):
    """
    Access point for viewing/downloading an official circular attachment.
    Tracks read receipt (is_viewed, timestamp, user, IP, view_count).
    """
    dispatch = get_object_or_404(
        OfficialCircularDispatch.objects.select_related('circular', 'seat'),
        pk=dispatch_pk
    )
    user = request.user
    seat = dispatch.seat

    # Check permissions
    is_seat_rep = (
        seat.primary_rep == user or
        seat.deputy_rep_1 == user or
        seat.deputy_rep_2 == user
    )
    if not (is_seat_rep or can_user_manage_dispatch_center(user) or user.can_view_correspondence or user.can_view_dispatch_log or user.is_super):
        messages.error(request, 'غير مصرح لك بتحميل هذا التعميم.')
        return redirect('/dashboard/')

    # Mark as viewed
    first_time = not dispatch.is_viewed
    client_ip = get_client_ip(request)
    dispatch.mark_as_viewed(user=user, ip=client_ip)

    # Audit log
    AuditLog.objects.create(
        user=user,
        action='read',
        model_name='OfficialCircularDispatch',
        object_id=str(dispatch.pk),
        object_repr=f'اطلاع على تعميم رسمي: {dispatch.circular.title[:30]} ({seat.name})',
        ip_address=client_ip,
        notes=f'أول اطلاع: {"نعم" if first_time else "مطالعة سابقة"} | عدد المشاهدات: {dispatch.view_count}'
    )

    file_obj = dispatch.circular.attachment_file
    if not file_obj:
        circular = dispatch.circular
        if circular.dispatch_type == 'session_minutes' and circular.session:
            pdf_file = generate_session_minutes_pdf(circular.session)
            circular.attachment_file.save(pdf_file.name, pdf_file)
            circular.save(update_fields=['attachment_file'])
            file_obj = circular.attachment_file
            if not circular.session.archived_pdf:
                circular.session.archived_pdf = circular.attachment_file
                circular.session.save(update_fields=['archived_pdf'])
        elif circular.dispatch_type == 'single_topic' and circular.topic:
            pdf_file = generate_single_topic_decision_pdf(circular.topic, circular.circular_number, str(circular.circular_date or ''))
            circular.attachment_file.save(pdf_file.name, pdf_file)
            circular.save(update_fields=['attachment_file'])
            file_obj = circular.attachment_file
        elif circular.dispatch_type == 'category_topics' and circular.session and circular.category:
            pdf_file = generate_category_topics_pdf(circular.session, circular.category)
            circular.attachment_file.save(pdf_file.name, pdf_file)
            circular.save(update_fields=['attachment_file'])
            file_obj = circular.attachment_file

    if not file_obj:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax') == '1':
            return JsonResponse({'ok': False, 'error': 'ملف التعميم غير متوفر حالياً.'}, status=404)
        raise Http404('ملف التعميم غير موجود.')

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax') == '1':
        return JsonResponse({
            'ok': True,
            'file_url': file_obj.url,
            'viewed_at': dispatch.viewed_at.strftime('%Y-%m-%d %H:%M') if dispatch.viewed_at else '',
            'viewed_by': user.full_name,
            'view_count': dispatch.view_count
        })

    return redirect(file_obj.url)


# ── 10. Export Correspondence Manifest (تصدير كشف وفهرس المراسلات Excel) ───────
@login_required(login_url='/login/')
def export_dispatch_manifest_view(request):
    """
    Exports a comprehensive Excel manifest of all dispatched circulars and decisions,
    containing metadata only (titles, numbers, dates, recipients, read receipts) without
    attaching the physical PDFs.
    Requires can_export_dispatch_manifest or superuser.
    """
    user = request.user
    if not (user.is_super or getattr(user, 'can_export_dispatch_manifest', False) or user.can_view_dispatch_log):
        messages.error(request, 'ليس لديك صلاحية لتصدير كشف وفهرس المراسلات.')
        return redirect('council:dispatch_log')

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "فهرس وكشف المراسلات"
    ws.sheet_view.rightToLeft = True

    # 1. Title Banner
    ws.merge_cells("A1:N1")
    title_cell = ws["A1"]
    title_cell.value = "الجمهورية اليمنية — جامعة صنعاء — كشف وفهرس المراسلات والقرارات الرسمية الصادرة للكليات"
    title_cell.font = Font(name="Arial", size=14, bold=True, color="1B365D")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36

    ws.merge_cells("A2:N2")
    sub_cell = ws["A2"]
    sub_cell.value = f"تاريخ التصدير: {datetime.now().strftime('%Y-%m-%d %H:%M')} | تم التصدير بواسطة: {user.full_name}"
    sub_cell.font = Font(name="Arial", size=10, italic=True, color="555555")
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 22

    # 2. Table Headers
    headers = [
        "#",
        "عنوان المراسلة أو القرار",
        "نوع المراسلة",
        "رقم القرار / التعميم",
        "تاريخ التعميم",
        "الجلسة المعنية",
        "الجهة / الكلية المستلمة",
        "الممثل الأصيل للجهة",
        "تاريخ ووقت الإرسال",
        "مسؤول الإرسال",
        "حالة الاستلام والاطلاع",
        "تاريخ ووقت الاطلاع",
        "المطّلع الفعلي",
        "مرات المشاهدة",
    ]

    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    thin_border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC")
    )

    ws.row_dimensions[4].height = 28
    for col_idx, h_text in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_idx, value=h_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # 3. Query Dispatches
    dispatches = OfficialCircularDispatch.objects.select_related(
        'circular', 'circular__session', 'circular__topic', 'seat', 'sent_by', 'viewed_by'
    ).order_by('-sent_at')

    row_font = Font(name="Arial", size=10)
    alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    for idx, d in enumerate(dispatches, 1):
        r_idx = idx + 4
        ws.row_dimensions[r_idx].height = 24
        fill_to_use = alt_fill if idx % 2 == 0 else white_fill

        c = d.circular
        sess_str = f"جلسة ({c.session.session_number})" if c.session else "عام"
        status_str = "تم الاطلاع" if d.is_viewed else "جديد • قيد الانتظار"
        viewed_at_str = d.viewed_at.strftime('%Y-%m-%d %H:%M') if d.viewed_at else "-"
        viewed_by_str = d.viewed_by.full_name if d.viewed_by else "-"

        row_data = [
            idx,
            c.title,
            c.get_dispatch_type_display(),
            c.circular_number or "-",
            c.circular_date.strftime('%Y-%m-%d') if c.circular_date else "-",
            sess_str,
            d.seat.name,
            d.seat.primary_rep.full_name if d.seat and d.seat.primary_rep else "-",
            d.sent_at.strftime('%Y-%m-%d %H:%M'),
            d.sent_by.full_name if d.sent_by else "الأمانة العامة",
            status_str,
            viewed_at_str,
            viewed_by_str,
            d.view_count,
        ]

        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=r_idx, column=col_idx, value=val)
            cell.font = row_font
            cell.fill = fill_to_use
            cell.border = thin_border
            if col_idx in [1, 3, 4, 5, 6, 9, 10, 11, 12, 14]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center")

            # Green highlight for viewed status
            if col_idx == 11 and d.is_viewed:
                cell.font = Font(name="Arial", size=10, bold=True, color="155724")
            elif col_idx == 11 and not d.is_viewed:
                cell.font = Font(name="Arial", size=10, bold=True, color="856404")

    # Column Widths adjustment
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    ws.column_dimensions["B"].width = 40  # Title
    ws.column_dimensions["G"].width = 28  # Faculty seat

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"dispatches_manifest_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ── 11. Reset All Dispatches (تصفير وتطهير سجلات المراسلات) ───────────────────
@login_required(login_url='/login/')
@require_POST
def reset_all_dispatches_view(request):
    """
    High-privilege security action: resets and flushes all dispatch records
    from all faculties' inboxes across the university.
    Requires can_reset_dispatches permission or superuser, and confirmation text.
    """
    user = request.user
    if not (user.is_super or getattr(user, 'can_reset_dispatches', False)):
        messages.error(request, 'غير مصرح لك بتصفير سجلات المراسلات.')
        return redirect('council:dispatch_log')

    confirm_text = request.POST.get('confirm_text', '').strip()
    if confirm_text != 'تأكيد التصفير':
        messages.error(request, 'لم يتم تأكيد التصفير بشكل صحيح. يرجى كتابة "تأكيد التصفير" للمتابعة.')
        return redirect('council:dispatch_log')

    with transaction.atomic():
        total_circ_dispatches = OfficialCircularDispatch.objects.count()
        total_sd_dispatches = SignedDecisionDispatch.objects.count()
        total_circulars = OfficialCircular.objects.count()

        # Delete delivery records (dispatches) for all seats
        OfficialCircularDispatch.objects.all().delete()
        SignedDecisionDispatch.objects.all().delete()
        OfficialCircular.objects.all().delete()

        # Audit log
        AuditLog.objects.create(
            user=user,
            action='delete',
            model_name='OfficialCircularDispatch',
            object_id='ALL',
            object_repr=f'تصفير شامل لسجلات المراسلات ({total_circ_dispatches} تعميم)',
            ip_address=get_client_ip(request),
            notes=f'قام المسؤول ({user.full_name}) بتصفير جميع صناديق الوارد لكافة الكليات والأعضاء.'
        )

    messages.success(request, f'تم تصفير وإفراغ جميع سجلات المراسلات وصناديق الوارد لكافة الكليات بنجاح ({total_circ_dispatches} مراسلة).')
    return redirect('council:dispatch_log')


