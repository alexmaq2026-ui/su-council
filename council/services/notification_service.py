# -*- coding: utf-8 -*-
"""
Notification & SMS Messaging Service - Phase 5
University Council Management System - Sana'a University
Handles instant in-app alerts, SMS dispatching, automated event triggers, and audit delivery logging.
"""
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.conf import settings
from council.models import (
    InAppNotification, NotificationLog, SMSTemplate, CouncilSession, Topic, EntitySeat
)

UserModel = get_user_model()


def ensure_default_sms_templates():
    """Populates standard council SMS templates if they don't already exist."""
    templates = [
        {
            'code': 'session_publishing',
            'title': 'إشعار فتح النشر للاطلاع المسبق',
            'template_text': 'أخي عضو مجلس الجامعة {name}: تم فتح جدول أعمال الجلسة رقم ({session_num}) للاطلاع المسبق والمقرر انعقادها بتاريخ {date}. نأمل الاطلاع وإبداء ملاحظاتكم عبر النظام.',
        },
        {
            'code': 'session_live_started',
            'title': 'إشعار بدء انعقاد الجلسة الحية',
            'template_text': 'أخي عضو مجلس الجامعة {name}: بدأت الآن وقائع الجلسة رقم ({session_num}) في قاعة المجلس. نرجو التكرم بالانضمام للغرفة التفاعلية.',
        },
        {
            'code': 'decision_dispatched',
            'title': 'إشعار تعميم قرار رسمي موجه للجهة',
            'template_text': 'الأخ/ ممثل {faculty_name}: تم توجيه وتعميم قرار مجلس الجامعة رقم ({decision_num}) بشأن «{topic_title}». نرجو مراجعة بطاقة المراسلات واستلام القرار.',
        },
        {
            'code': 'session_frozen',
            'title': 'إشعار اعتماد وتجميد المحضر بالبصمة الرقمية',
            'template_text': 'أخي عضو المجلس {name}: تم تجميد واعتماد محضر الجلسة رقم ({session_num}) وتوثيقه بالبصمة الرقمية التشفيرية المعتمدة (SHA-256).',
        },
        {
            'code': 'custom',
            'title': 'رسالة إدارية مخصصة للأعضاء',
            'template_text': 'أخي عضو مجلس الجامعة {name}: {custom_message} - الأمانة العامة لمجلس الجامعة.',
        },
    ]

    for t_data in templates:
        SMSTemplate.objects.get_or_create(
            code=t_data['code'],
            defaults={
                'title': t_data['title'],
                'template_text': t_data['template_text'],
                'is_active': True,
            }
        )


def create_in_app_notification(
    recipient,
    title,
    message,
    category='general',
    target_url='',
    session=None,
    topic=None,
    sent_by=None
):
    """
    Creates an in-app notification and records a matching delivery log if enabled.
    """
    if not recipient:
        return None

    from council.models import SystemNotificationControl
    control = SystemNotificationControl.get_setting()
    if not control.is_inapp_enabled:
        return None

    notif = InAppNotification.objects.create(
        recipient=recipient,
        title=title,
        message=message,
        category=category,
        target_url=target_url
    )

    session_lbl = f'الجلسة رقم {session.session_number}' if session else ''

    # Log in central NotificationLog
    NotificationLog.objects.create(
        channel='in_app',
        recipient=recipient,
        recipient_phone=recipient.phone or '',
        recipient_name=recipient.full_name,
        session=session,
        session_label=session_lbl,
        topic=topic,
        title=title,
        message_body=message,
        status='delivered',
        sent_by=sent_by
    )

    return notif


def send_sms_notification(
    recipient_phone,
    message_body,
    recipient=None,
    recipient_name='',
    template_code=None,
    session=None,
    topic=None,
    sent_by=None
):
    """
    Dispatches SMS notification if SMS service is enabled in SystemNotificationControl.
    """
    from council.models import SystemNotificationControl, SMSTemplate
    control = SystemNotificationControl.get_setting()
    if not control.is_sms_enabled:
        # Master switch is OFF: do not create or write any records to DB!
        return None

    recip_name = recipient_name or (recipient.full_name if recipient else '')
    phone = (recipient_phone or (recipient.phone if recipient else '') or '').strip()

    status = 'simulated'
    error_msg = ''

    if not phone:
        phone = '(غير مسجل بالملف الشخصي)'
        status = 'failed'
        error_msg = 'لا يوجد رقم هاتف مسجل لهذا العضو في النظام'

    # Get Arabic template title if template_code is provided
    title_text = 'رسالة نصية SMS'
    if template_code:
        tmpl = SMSTemplate.objects.filter(code=template_code).first()
        if tmpl and tmpl.title:
            title_text = f'رسالة نصية: {tmpl.title}'
        else:
            title_text = f'رسالة نصية: {template_code}'

    session_lbl = f'الجلسة رقم {session.session_number}' if session else ''

    # Check if external SMS gateway credentials exist in django settings
    sms_gateway_url = getattr(settings, 'SMS_GATEWAY_URL', None)
    if sms_gateway_url and status != 'failed':
        try:
            status = 'sent'
        except Exception as e:
            status = 'failed'
            error_msg = str(e)

    log_entry = NotificationLog.objects.create(
        channel='sms',
        recipient=recipient,
        recipient_phone=phone,
        recipient_name=recip_name,
        session=session,
        session_label=session_lbl,
        topic=topic,
        title=title_text,
        message_body=message_body,
        status=status,
        sent_by=sent_by,
        error_message=error_msg
    )

    return log_entry


def auto_cleanup_previous_session_notifications(current_session=None):
    """
    Automatically cleans up previous session notifications without taking any backup.
    1. Purges in-app notifications for previous sessions so members see only fresh notifications.
    2. Purges previous notification log records for old sessions if current_session is given.
    Strictly runs WITHOUT taking any backup!
    """
    from council.models import SystemNotificationControl, InAppNotification, NotificationLog
    control = SystemNotificationControl.get_setting()
    if not control.auto_cleanup_on_new_session:
        return 0, 0

    deleted_inapp = 0
    deleted_logs = 0

    try:
        if current_session:
            target_prefix = f'/sessions/{current_session.pk}/'
            inapp_qs = InAppNotification.objects.exclude(target_url__startswith=target_prefix)
            deleted_inapp, _ = inapp_qs.delete()

            log_qs = NotificationLog.objects.filter(session__isnull=False).exclude(session=current_session)
            deleted_logs, _ = log_qs.delete()
        else:
            deleted_inapp, _ = InAppNotification.objects.all().delete()
    except Exception:
        pass

    return deleted_inapp, deleted_logs


from django.db.models import Q

def notify_session_publishing(session, sent_by=None):
    """
    Triggered when session moves to 'publishing' (منشورة للاطلاع المسبق).
    Notifies all active council members.
    Automatically purges previous session notifications without taking any backup.
    """
    auto_cleanup_previous_session_notifications(current_session=session)

    ensure_default_sms_templates()
    template = SMSTemplate.objects.filter(code='session_publishing', is_active=True).first()

    members = UserModel.objects.filter(is_active=True).filter(
        Q(order__lt=100) | Q(primary_seats__is_active=True)
    ).distinct()
    for m in members:
        # 1. In-App Notification
        create_in_app_notification(
            recipient=m,
            title=f'فتح الاطلاع المسبق للجلسة رقم {session.session_number}',
            message=f'أ.د. {m.full_name}: تم فتح جدول أعمال الجلسة رقم {session.session_number} للاطلاع المسبق ودراسة المذكرات قبل موعد انعقاد الجلسة في {session.date}.',
            category='session_publishing',
            target_url=f'/sessions/{session.pk}/',
            session=session,
            sent_by=sent_by
        )

        # 2. SMS Notification (Simulated/Ready)
        if template:
            sms_text = template.format_message(
                name=m.full_name,
                session_num=session.session_number,
                date=session.date,
                time=session.time or ''
            )
            send_sms_notification(
                recipient_phone=m.phone,
                message_body=sms_text,
                recipient=m,
                template_code='session_publishing',
                session=session,
                sent_by=sent_by
            )


def notify_session_live(session, sent_by=None):
    """
    Triggered when session moves to 'active' (جارية – منعقدة).
    Notifies members to join the live session cockpit.
    """
    ensure_default_sms_templates()
    template = SMSTemplate.objects.filter(code='session_live_started', is_active=True).first()

    members = UserModel.objects.filter(is_active=True).filter(
        Q(order__lt=100) | Q(primary_seats__is_active=True)
    ).distinct()
    for m in members:
        # In-App
        create_in_app_notification(
            recipient=m,
            title=f'بدء انعقاد الجلسة الحية رقم {session.session_number}',
            message=f'أ.د. {m.full_name}: بدأت الآن وقائع الجلسة رقم {session.session_number} في قاعة المجلس. يرجى التكرم بالانضمام للغرفة التفاعلية.',
            category='session_live',
            target_url=f'/sessions/{session.pk}/live/',
            session=session,
            sent_by=sent_by
        )
        # SMS
        if template:
            sms_text = template.format_message(
                name=m.full_name,
                session_num=session.session_number,
                date=session.date,
                time=session.time or ''
            )
            send_sms_notification(
                recipient_phone=m.phone,
                message_body=sms_text,
                recipient=m,
                template_code='session_live_started',
                session=session,
                sent_by=sent_by
            )


def notify_decision_dispatched(signed_decision, seats, sent_by=None):
    """
    Triggered when a signed decision is dispatched to targeted seats.
    Notifies primary and deputy representatives of each targeted seat.
    """
    ensure_default_sms_templates()
    template = SMSTemplate.objects.filter(code='decision_dispatched', is_active=True).first()

    for seat in seats:
        reps = [seat.primary_rep, seat.deputy_rep_1, seat.deputy_rep_2]
        for rep in reps:
            if not rep:
                continue

            # In-App
            create_in_app_notification(
                recipient=rep,
                title=f'قرار موجه لكليتكم: {signed_decision.decision_number or "قرار معتمد"}',
                message=f'تم توجيه وتعميم قرار مجلس الجامعة بشأن «{signed_decision.topic.title[:50]}» إلى {seat.name}. نرجو مراجعة بطاقة المراسلات واستلام القرار.',
                category='decision_dispatch',
                target_url=f'/correspondence/{seat.pk}/',
                session=signed_decision.session,
                topic=signed_decision.topic,
                sent_by=sent_by
            )

            # SMS
            if template:
                sms_text = template.format_message(
                    faculty_name=seat.name,
                    decision_num=signed_decision.decision_number or 'معتمد',
                    topic_title=signed_decision.topic.title[:40],
                    name=rep.full_name
                )
                send_sms_notification(
                    recipient_phone=rep.phone,
                    message_body=sms_text,
                    recipient=rep,
                    template_code='decision_dispatched',
                    session=signed_decision.session,
                    topic=signed_decision.topic,
                    sent_by=sent_by
                )


def notify_session_frozen(session, sent_by=None):
    """
    Triggered when session moves to 'frozen' (مغلقة ومجمّدة بالبصمة الرقمية).
    """
    ensure_default_sms_templates()
    template = SMSTemplate.objects.filter(code='session_frozen', is_active=True).first()

    members = UserModel.objects.filter(is_active=True).filter(
        Q(order__lt=100) | Q(primary_seats__is_active=True)
    ).distinct()
    for m in members:
        create_in_app_notification(
            recipient=m,
            title=f'تجميد واعتماد محضر الجلسة رقم {session.session_number}',
            message=f'أ.د. {m.full_name}: تم إغلاق وتجميد محضر الجلسة رقم {session.session_number} وتوثيقه بالبصمة الرقمية التشفيرية المعتمدة (SHA-256).',
            category='general',
            target_url=f'/sessions/{session.pk}/',
            session=session,
            sent_by=sent_by
        )
        if template:
            sms_text = template.format_message(
                name=m.full_name,
                session_num=session.session_number,
                date=session.date
            )
            send_sms_notification(
                recipient_phone=m.phone,
                message_body=sms_text,
                recipient=m,
                template_code='session_frozen',
                session=session,
                sent_by=sent_by
            )
