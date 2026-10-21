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

    from council.models import SystemNotificationControl
    control = SystemNotificationControl.get_setting()

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
        'control': control,
        'user_can_toggle_sms': user.is_super or getattr(user, 'can_toggle_sms', False),
        'user_can_toggle_inapp': user.is_super or getattr(user, 'can_toggle_inapp', False),
        'user_can_clear_log': user.is_super or getattr(user, 'can_clear_notification_log', False),
        'user_can_manual_backup': user.is_super or getattr(user, 'can_manual_backup_notifications', False),
    }
    return render(request, 'council/notification_log.html', context)


@login_required(login_url='/login/')
@require_POST
def toggle_notification_service_view(request):
    """
    Toggle In-App or SMS notification service on/off.
    Requires can_toggle_inapp or can_toggle_sms permission.
    """
    user = request.user
    service_type = request.POST.get('service_type')  # 'inapp' or 'sms'

    from council.models import SystemNotificationControl
    control = SystemNotificationControl.get_setting()

    if service_type == 'sms':
        if not (user.is_super or getattr(user, 'can_toggle_sms', False)):
            messages.error(request, 'عذراً، ليس لديك صلاحية لإيقاف أو تشغيل رسائل SMS.')
            return redirect('council:notification_log')
        control.is_sms_enabled = not control.is_sms_enabled
        control.updated_by = user
        control.save(update_fields=['is_sms_enabled', 'updated_by', 'updated_at'])
        state = 'تشغيل وتفعيل' if control.is_sms_enabled else 'إيقاف وتعطيل'
        messages.success(request, f'تم {state} خدمة الرسائل النصية القصيرة SMS بنجاح.')

    elif service_type == 'inapp':
        if not (user.is_super or getattr(user, 'can_toggle_inapp', False)):
            messages.error(request, 'عذراً، ليس لديك صلاحية لإيقاف أو تشغيل إشعارات النظام.')
            return redirect('council:notification_log')
        control.is_inapp_enabled = not control.is_inapp_enabled
        control.updated_by = user
        control.save(update_fields=['is_inapp_enabled', 'updated_by', 'updated_at'])
        state = 'تشغيل وتفعيل' if control.is_inapp_enabled else 'إيقاف وتعطيل'
        messages.success(request, f'تم {state} إشعارات النظام المباشرة للأعضاء بنجاح.')

    return redirect('council:notification_log')


@login_required(login_url='/login/')
@require_POST
def clear_notification_log_view(request):
    """
    Purge and clear notification logs permanently WITHOUT TAKING ANY BACKUP.
    Requires can_clear_notification_log or superuser.
    """
    user = request.user
    if not (user.is_super or getattr(user, 'can_clear_notification_log', False)):
        messages.error(request, 'عذراً، ليس لديك صلاحية لتصفير ومسح سجلات التنبيهات.')
        return redirect('council:notification_log')

    purge_mode = request.POST.get('purge_mode', 'all')  # 'all', 'sms_only', 'old_sessions'

    from council.models import NotificationLog, InAppNotification, CouncilSession

    if purge_mode == 'sms_only':
        deleted_count, _ = NotificationLog.objects.filter(channel='sms').delete()
        messages.success(request, f'تم تصفير وحذف كافة رسائل الـ SMS ({deleted_count} رسالة) بنجاح ودون أخذ أي نسخة احتياطية.')
    elif purge_mode == 'old_sessions':
        latest_session = CouncilSession.objects.order_by('-date', '-session_number').first()
        if latest_session:
            deleted_count, _ = NotificationLog.objects.exclude(session=latest_session).delete()
            InAppNotification.objects.exclude(target_url__contains=f'/sessions/{latest_session.pk}/').delete()
            messages.success(request, f'تم حذف إشعارات الجلسات السابقة ({deleted_count} سجل) والإبقاء على الجلسة الحالية فقط بنجاح دون أي نسخ احتياطي.')
        else:
            deleted_count, _ = NotificationLog.objects.all().delete()
            InAppNotification.objects.all().delete()
            messages.success(request, 'تم تصفير سجلات التنبيهات بالكامل بنجاح.')
    else:
        # Full clear: delete all notification logs and in-app notifications
        deleted_count, _ = NotificationLog.objects.all().delete()
        InAppNotification.objects.all().delete()
        messages.success(request, f'تم تصفير ومسح كافة سجلات التنبيهات والإشعارات ({deleted_count} سجل) نهائياً بنجاح ودون أخذ أي نسخة احتياطية.')

    return redirect('council:notification_log')


@login_required(login_url='/login/')
def manual_backup_notifications_view(request):
    """
    Explicit manual backup for notification logs (downloadable JSON).
    Executes ONLY when manually requested by authorized user.
    Requires can_manual_backup_notifications or superuser.
    """
    user = request.user
    if not (user.is_super or getattr(user, 'can_manual_backup_notifications', False)):
        messages.error(request, 'عذراً، ليس لديك صلاحية لأخذ نسخة احتياطية لسجلات التنبيهات.')
        return redirect('council:notification_log')

    import json
    from django.http import HttpResponse
    from django.utils import timezone
    from council.models import NotificationLog

    logs = list(NotificationLog.objects.all().values(
        'id', 'channel', 'recipient_name', 'recipient_phone',
        'title', 'message_body', 'status', 'session_id', 'session_label', 'sent_at'
    ))
    for l in logs:
        if l.get('sent_at'):
            l['sent_at'] = l['sent_at'].isoformat()

    json_data = json.dumps(logs, ensure_ascii=False, indent=2)
    response = HttpResponse(json_data, content_type='application/json; charset=utf-8')
    filename = f'notifications_backup_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


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
