# -*- coding: utf-8 -*-
"""
Notification & SMS Management Views - Phase 5
University Council Management System - Sana'a University
Handles:
- In-App Notification Bell & Real-time fetch API
- Mark as Read / Mark All as Read APIs
- User Notifications Center (notification_list_view)
- Central Notification & SMS Delivery Log for Secretariat (notification_log_view)
- SMS Templates Management (sms_template_list_view, sms_template_edit_view)
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse, HttpResponseForbidden, Http404
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q

from council.models import (
    InAppNotification, NotificationLog, SMSTemplate, CouncilSession, Topic, AuditLog
)
from council.services.notification_service import (
    ensure_default_sms_templates, send_sms_notification, create_in_app_notification
)


def get_client_ip(request):
    """Utility to extract real client IP address."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


# ── 1. In-App Notifications API (Bell Dropdown & Polling) ─────────────────────

@login_required(login_url='/login/')
@require_GET
def api_unread_notifications(request):
    """
    Returns unread count and latest 7 notifications for current user in JSON format.
    Used by top-bar notification bell dropdown.
    Requires can_view_notifications permission.
    """
    user = request.user
    if not (user.is_super or user.can_view_notifications):
        return JsonResponse({'ok': False, 'unread_count': 0, 'notifications': [], 'error': 'غير مصرح.'}, status=403)

    qs = InAppNotification.objects.filter(recipient=user)
    unread_count = qs.filter(is_read=False).count()
    latest_notifs = qs.order_by('-created_at')[:7]

    data = []
    for n in latest_notifs:
        data.append({
            'id': n.id,
            'title': n.title,
            'message': n.message[:120] + ('...' if len(n.message) > 120 else ''),
            'category': n.category,
            'category_display': n.get_category_display(),
            'target_url': n.target_url or '',
            'is_read': n.is_read,
            'created_at': n.created_at.strftime('%Y-%m-%d %H:%M'),
        })

    return JsonResponse({
        'ok': True,
        'unread_count': unread_count,
        'notifications': data
    })


@login_required(login_url='/login/')
@require_POST
def api_mark_notification_read(request, notif_pk):
    """
    Marks a specific notification as read.
    """
    if not (request.user.is_super or request.user.can_view_notifications):
        return JsonResponse({'ok': False, 'error': 'غير مصرح.'}, status=403)

    notif = get_object_or_404(InAppNotification, pk=notif_pk, recipient=request.user)
    notif.mark_as_read()
    return JsonResponse({'ok': True, 'id': notif.pk, 'is_read': True})


@login_required(login_url='/login/')
@require_POST
def api_mark_all_notifications_read(request):
    """
    Marks all notifications for current user as read.
    """
    if not (request.user.is_super or request.user.can_view_notifications):
        return JsonResponse({'ok': False, 'error': 'غير مصرح.'}, status=403)

    InAppNotification.objects.filter(recipient=request.user, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )
    return JsonResponse({'ok': True, 'message': 'تم تحديد كافة الإشعارات كمقروءة.'})


# ── 2. Full In-App Notifications Center Page ─────────────────────────────────

@login_required(login_url='/login/')
def notification_list_view(request):
    """
    Full page listing all notifications for the logged in user with filters and pagination.
    Requires can_view_notifications.
    """
    user = request.user
    if not (user.is_super or user.can_view_notifications):
        messages.error(request, 'ليس لديك صلاحية لاستعراض مركز الإشعارات والتنبيهات.')
        return redirect('/dashboard/')

    status_filter = request.GET.get('status')  # 'unread', 'read', or all

    qs = InAppNotification.objects.filter(recipient=user).order_by('-created_at')
    if status_filter == 'unread':
        qs = qs.filter(is_read=False)
    elif status_filter == 'read':
        qs = qs.filter(is_read=True)

    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    unread_count = InAppNotification.objects.filter(recipient=user, is_read=False).count()

    context = {
        'page_obj': page_obj,
        'unread_count': unread_count,
        'total_count': InAppNotification.objects.filter(recipient=user).count(),
        'status_filter': status_filter or 'all',
    }
    return render(request, 'council/notification_list.html', context)


# ── 3. Central Notification & SMS Delivery Log (Secretariat & Admins) ────────

@login_required(login_url='/login/')
def notification_log_view(request):
    """
    Central delivery log for Secretariat & President.
    Monitors all outbound notifications across channels (In-App & SMS).
    Requires can_view_notification_log.
    """
    user = request.user
    if not (user.is_super or getattr(user, 'can_view_notification_log', False)):
        messages.error(request, 'ليس لديك صلاحية لاستعراض سجل تسليم التنبيهات.')
        return redirect('/dashboard/')

    channel = request.GET.get('channel')  # 'in_app', 'sms'
    status = request.GET.get('status')
    session_id = request.GET.get('session')
    search_q = request.GET.get('q', '').strip()

    qs = NotificationLog.objects.select_related('recipient', 'session', 'topic', 'sent_by').order_by('-sent_at')

    if channel:
        qs = qs.filter(channel=channel)
    if status:
        qs = qs.filter(status=status)
    if session_id:
        qs = qs.filter(session_id=session_id)
    if search_q:
        qs = qs.filter(
            Q(recipient_name__icontains=search_q) |
            Q(recipient_phone__icontains=search_q) |
            Q(title__icontains=search_q) |
            Q(message_body__icontains=search_q)
        )

    total_logs = qs.count()
    sms_count = qs.filter(channel='sms').count()
    in_app_count = qs.filter(channel='in_app').count()

    paginator = Paginator(qs, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    sessions = CouncilSession.objects.order_by('-session_number')[:15]

    context = {
        'page_obj': page_obj,
        'total_logs': total_logs,
        'sms_count': sms_count,
        'in_app_count': in_app_count,
        'sessions': sessions,
        'selected_channel': channel,
        'selected_status': status,
        'selected_session': session_id,
        'search_q': search_q,
    }
    return render(request, 'council/notification_log.html', context)


# ── 4. SMS Templates Management (can_manage_sms_template) ────────────────────

@login_required(login_url='/login/')
def sms_template_list_view(request):
    """
    List and manage customizable SMS templates for the council.
    Requires can_manage_sms_template or superuser.
    """
    user = request.user
    if not (user.is_super or getattr(user, 'can_manage_sms_template', False)):
        messages.error(request, 'ليس لديك صلاحية لإدارة قوالب الرسائل النصية SMS.')
        return redirect('/dashboard/')

    ensure_default_sms_templates()
    templates = SMSTemplate.objects.all().order_by('code')

    context = {
        'templates': templates,
    }
    return render(request, 'council/sms_template_list.html', context)


@login_required(login_url='/login/')
@require_POST
def sms_template_edit_view(request, pk):
    """
    Update a specific SMS template's text or active state.
    """
    user = request.user
    if not (user.is_super or getattr(user, 'can_manage_sms_template', False)):
        messages.error(request, 'ليس لديك صلاحية لتعديل قوالب الرسائل النصية.')
        return redirect('/dashboard/')

    template = get_object_or_404(SMSTemplate, pk=pk)
    title = request.POST.get('title', '').strip()
    template_text = request.POST.get('template_text', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not title or not template_text:
        messages.error(request, 'يجب إدخال اسم القالب ونصه بالكامل.')
        return redirect('council:sms_template_list')

    template.title = title
    template.template_text = template_text
    template.is_active = is_active
    template.save()

    AuditLog.objects.create(
        user=user,
        action='update',
        model_name='SMSTemplate',
        object_id=str(template.pk),
        object_repr=f'تحديث قالب الرسائل النصية ({template.title})',
        ip_address=get_client_ip(request),
        notes=f'الرمز: {template.code}'
    )

    messages.success(request, f'تم تحديث قالب «{template.title}» بنجاح.')
    return redirect('council:sms_template_list')
