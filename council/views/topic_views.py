"""
Topic Views
University Council Management System

Handles: topic detail/create/edit/delete/status change,
         attachments, recordings, and Word import.
"""
import os
import json

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings
from django.core.files.base import ContentFile

from council.models import (
    CouncilSession, Topic, TopicAttachment, TopicRecording,
    TOPIC_CATEGORIES, TOPIC_STATUS,
)
from council.forms import TopicForm, AttachmentForm
from council.forms.topic_forms import RecordingLabelForm
from council.services.word_import import parse_word_file


# ── Topic Detail ───────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def topic_detail_view(request, pk):
    """
    Full topic details: background, priorities, attachments,
    recordings, vote results, and decision.
    Requires can_view_topics permission.
    """
    if not (request.user.is_super or request.user.can_view_topics):
        messages.error(request, 'ليس لديك صلاحية لعرض تفاصيل المواضيع.')
        return redirect('/dashboard/')

    topic = get_object_or_404(
        Topic.objects
        .select_related('session', 'created_by', 'decision', 'signed_decision', 'display_state')
        .prefetch_related(
            'attachments', 'attachments__uploaded_by',
            'recordings', 'recordings__recorded_by',
            'votes', 'votes__member',
            'tables', 'target_seats',
        ),
        pk=pk
    )
    if not topic.session.can_be_seen_by(request.user):
        if topic.session.status == 'draft':
            messages.error(request, 'هذه الجلسة في مرحلة التحضير ولا يمكن الاطلاع على مواضيعها حالياً.')
        else:
            messages.error(request, 'ليس لديك صلاحية للاطلاع على مواضيع ومرفقات الجلسات السابقة.')
        return redirect('/dashboard/')

    user = request.user
    editable = not topic.session.is_frozen()
    vote_summary  = topic.get_vote_summary()
    user_vote     = topic.get_user_vote(user)
    has_decision  = topic.has_decision()
    from council.models import EntitySeat
    all_seats = EntitySeat.objects.filter(is_active=True).order_by('order', 'name')

    context = {
        'topic':        topic,
        'session':      topic.session,
        'vote_summary': vote_summary,
        'user_vote':    user_vote,
        'has_decision': has_decision,
        'decision':     topic.decision if has_decision else None,
        'all_seats':    all_seats,
        'page_title':   topic.title,
        'user_can_add':    user.can_add and editable,
        'user_can_edit':   user.can_edit and editable,
        'user_can_delete': user.can_delete and editable,
        'user_can_edit_topic':         (user.is_super or user.can_edit_topic) and editable,
        'user_can_delete_topic':       (user.is_super or user.can_delete_topic) and editable,
        'user_can_change_topic_status':(user.is_super or user.can_change_topic_status) and editable,
        'user_can_add_table':          (user.is_super or user.can_add_table) and editable,
        'user_can_edit_table':         (user.is_super or user.can_edit_table) and editable,
        'user_can_delete_table':       (user.is_super or user.can_delete_table) and editable,
        'user_can_view_attachments':   (user.is_super or user.can_view_attachments or user.can_upload_attachments),
        'user_can_upload_attachments': (user.is_super or user.can_upload_attachments) and editable,
        'user_can_delete_attachments': (user.is_super or user.can_delete_attachments) and editable,
        'user_can_listen_audio':       (user.is_super or user.can_listen_audio or user.can_record_audio),
        'user_can_record_audio':       (user.is_super or user.can_record_audio) and editable,
        'user_can_delete_audio':       (user.is_super or user.can_delete_audio) and editable,
        'user_can_vote':               (user.is_super or user.can_vote) and topic.session.status == 'active',
        'user_can_view_vote_details':  (user.is_super or user.can_view_vote_details),
        'user_can_draft':              (user.is_super or user.can_draft_decision) and editable,
        'user_can_draft_decision':     (user.is_super or user.can_draft_decision) and editable,
        'user_can_delete_decision':    (user.is_super or user.can_delete_decision) and editable,
        'user_can_upload_signed':      (user.is_super or user.can_upload_signed_decision or user.can_send_decisions),
        'user_can_send_decisions':     (user.is_super or user.can_send_decisions),
        'is_controller':              (user.is_super or user.can_start_session_live),
        'user_can_use_smart_reader':   (user.is_super or user.can_use_smart_reader),
        'status_choices':  TOPIC_STATUS,
    }
    return render(request, 'council/topic_detail.html', context)


# ── Topic Create ───────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def topic_create_view(request, session_pk):
    """
    Create a new topic within a session. Requires can_add_topic.
    """
    if not (request.user.is_super or request.user.can_add_topic):
        messages.error(request, 'ليس لديك صلاحية لإضافة مواضيع.')
        return redirect('/dashboard/')

    session = get_object_or_404(CouncilSession, pk=session_pk)

    # حصر وتوجيه إعداد وإضافة الموضوعات في مرحلة التحضير للشاشة المخصصة حصرياً
    if session.status == 'draft':
        messages.info(request, 'يتم تجهيز وإعداد وإضافة موضوعات الجلسة حصرياً عبر شاشة إعداد جدول الأعمال المخصصة.')
        return redirect('council:session_prepare_edit', pk=session_pk)

    if request.method == 'POST':
        form = TopicForm(request.POST)
        if form.is_valid():
            topic = form.save(commit=False)
            topic.session    = session
            topic.created_by = request.user
            topic.save()
            messages.success(request, f'تم إضافة الموضوع "{topic.title}" بنجاح.')
            return redirect('council:topic_detail', pk=topic.pk)
    else:
        # Pre-fill order_number with next available
        next_order = (session.topics.count() or 0) + 1
        form = TopicForm(initial={'order_number': next_order})

    context = {
        'form':       form,
        'session':    session,
        'page_title': 'إضافة موضوع جديد',
        'action':     'create',
    }
    return render(request, 'council/topic_form.html', context)


# ── Topic Edit ─────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def topic_edit_view(request, pk):
    """
    Edit an existing topic. Requires can_edit_topic.
    """
    if not (request.user.is_super or request.user.can_edit_topic):
        messages.error(request, 'ليس لديك صلاحية لتعديل المواضيع.')
        return redirect('/dashboard/')

    topic = get_object_or_404(Topic.objects.select_related('session'), pk=pk)

    if request.method == 'POST':
        form = TopicForm(request.POST, instance=topic)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تحديث الموضوع بنجاح.')
            return redirect('council:topic_detail', pk=topic.pk)
    else:
        form = TopicForm(instance=topic)

    context = {
        'form':       form,
        'topic':      topic,
        'session':    topic.session,
        'page_title': f'تعديل الموضوع – {topic.title[:50]}',
        'action':     'edit',
    }
    return render(request, 'council/topic_form.html', context)


# ── Topic Delete ───────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def topic_delete_view(request, pk):
    """
    Delete a topic (POST confirmation required). Requires can_delete_topic.
    """
    if not (request.user.is_super or request.user.can_delete_topic):
        messages.error(request, 'ليس لديك صلاحية لحذف المواضيع.')
        return redirect('/dashboard/')

    topic = get_object_or_404(Topic.objects.select_related('session'), pk=pk)
    session_pk = topic.session.pk

    if request.method == 'POST':
        title = topic.title
        topic.delete()
        messages.success(request, f'تم حذف الموضوع "{title}" بنجاح.')
        return redirect('council:session_detail', pk=session_pk)

    context = {
        'topic':      topic,
        'session':    topic.session,
        'page_title': 'حذف الموضوع',
    }
    return render(request, 'council/topic_confirm_delete.html', context)


# ── Topic Status Change ────────────────────────────────────────────────────────

@login_required(login_url='/login/')
@require_POST
def topic_status_view(request, pk):
    """
    Change a topic's status via POST.
    Expects form field 'status'. Requires can_change_topic_status.
    """
    if not (request.user.is_super or request.user.can_change_topic_status):
        messages.error(request, 'ليس لديك صلاحية لتغيير حالة الموضوع.')
        return redirect('/dashboard/')

    topic = get_object_or_404(Topic, pk=pk)
    new_status = request.POST.get('status', '').strip()

    valid_statuses = [s[0] for s in TOPIC_STATUS]
    if new_status not in valid_statuses:
        messages.error(request, 'حالة غير صالحة.')
        return redirect('council:topic_detail', pk=pk)

    topic.status = new_status
    topic.save(update_fields=['status', 'updated_at'])

    status_label = dict(TOPIC_STATUS).get(new_status, new_status)
    messages.success(request, f'تم تغيير حالة الموضوع إلى "{status_label}".')
    return redirect('council:topic_detail', pk=pk)


# ── Attachment Upload ──────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def attachment_upload_view(request, topic_pk):
    """
    Upload a file attachment to a topic. Requires can_upload_attachments.
    GET:  Render upload form (usually partial/modal).
    POST: Save the uploaded file.
    """
    if not (request.user.is_super or request.user.can_upload_attachments):
        messages.error(request, 'ليس لديك صلاحية لرفع المرفقات.')
        return redirect('/dashboard/')

    topic = get_object_or_404(Topic.objects.select_related('session'), pk=topic_pk)

    if request.method == 'POST':
        form = AttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            attachment = form.save(commit=False)
            attachment.topic       = topic
            attachment.uploaded_by = request.user
            if request.FILES.get('file'):
                attachment.file_name = request.FILES['file'].name
            attachment.save()
            messages.success(request, f'تم رفع الملف "{attachment.file_name}" بنجاح.')
            return redirect('council:topic_detail', pk=topic.pk)
    else:
        form = AttachmentForm()

    context = {
        'form':       form,
        'topic':      topic,
        'session':    topic.session,
        'page_title': 'رفع مرفق',
    }
    return render(request, 'council/attachment_upload.html', context)


# ── Attachment Delete ──────────────────────────────────────────────────────────

@login_required(login_url='/login/')
@require_POST
def attachment_delete_view(request, pk):
    """
    Delete an attachment. Requires can_delete_attachments.
    """
    if not (request.user.is_super or request.user.can_delete_attachments):
        messages.error(request, 'ليس لديك صلاحية لحذف المرفقات.')
        return redirect('/dashboard/')

    attachment = get_object_or_404(TopicAttachment.objects.select_related('topic'), pk=pk)
    topic_pk   = attachment.topic.pk

    # Delete the physical file from storage
    if attachment.file:
        try:
            storage_path = attachment.file.path
            if os.path.isfile(storage_path):
                os.remove(storage_path)
        except Exception:
            pass  # Non-critical – DB record will still be deleted

    file_name = attachment.file_name
    attachment.delete()
    messages.success(request, f'تم حذف الملف "{file_name}" بنجاح.')
    return redirect('council:topic_detail', pk=topic_pk)


# ── Recording Save ─────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
@require_POST
def recording_save_view(request, topic_pk):
    """
    Save an audio recording blob sent via AJAX/fetch as multipart.
    Accepts: 'audio' or 'audio_blob' (file), 'label' (optional), 'duration' (int/float, seconds).
    Returns JSON response.
    Requires can_record_audio permission.
    """
    if not (request.user.is_super or request.user.can_record_audio):
        return JsonResponse(
            {'ok': False, 'success': False, 'error': 'ليس لديك صلاحية لتسجيل المداخلات الصوتية.'},
            status=403
        )

    topic = get_object_or_404(Topic, pk=topic_pk)

    audio_file = request.FILES.get('audio') or request.FILES.get('audio_blob')
    if not audio_file:
        return JsonResponse({'ok': False, 'success': False, 'error': 'لم يتم استلام ملف صوتي صالح.'}, status=400)

    label = request.POST.get('label', '').strip()
    try:
        duration = int(float(request.POST.get('duration', 0) or 0))
    except (ValueError, TypeError):
        duration = 0

    recording = TopicRecording.objects.create(
        topic            = topic,
        audio_file       = audio_file,
        duration_seconds = duration,
        label            = label,
        recorded_by      = request.user,
    )

    audio_url = recording.audio_file.url if recording.audio_file else ''

    return JsonResponse({
        'ok':           True,
        'success':      True,
        'recording_id': recording.pk,
        'id':           recording.pk,
        'label':        recording.label or f'تسجيل {recording.pk}',
        'duration':     recording.get_duration_display(),
        'audio_url':    audio_url,
        'recorded_at':  recording.recorded_at.strftime('%Y-%m-%d %H:%M'),
        'recording': {
            'id':           recording.pk,
            'label':        recording.label or f'تسجيل {recording.pk}',
            'duration':     recording.get_duration_display(),
            'audio_url':    audio_url,
            'recorded_at':  recording.recorded_at.strftime('%Y-%m-%d %H:%M'),
        }
    })


# ── Recording Delete ───────────────────────────────────────────────────────────

@login_required(login_url='/login/')
@require_POST
def recording_delete_view(request, pk):
    """
    Delete a recording. Requires can_delete_audio.
    """
    if not (request.user.is_super or request.user.can_delete_audio):
        messages.error(request, 'ليس لديك صلاحية لحذف التسجيلات الصوتية.')
        return redirect('/dashboard/')

    recording = get_object_or_404(TopicRecording.objects.select_related('topic'), pk=pk)
    topic_pk  = recording.topic.pk

    # Delete the physical file
    if recording.audio_file:
        try:
            storage_path = recording.audio_file.path
            if os.path.isfile(storage_path):
                os.remove(storage_path)
        except Exception:
            pass

    recording.delete()
    messages.success(request, 'تم حذف التسجيل الصوتي بنجاح.')
    return redirect('council:topic_detail', pk=topic_pk)


# ── Import Topics from Word ────────────────────────────────────────────────────

@login_required(login_url='/login/')
def import_word_view(request, session_pk):
    """
    Import topics from an uploaded Word (.docx) file into a session.
    Supports interactive preview, category filtering, and selective topic importing
    (import all or import specific topic(s)).
    Requires can_import_topics.
    """
    if not (request.user.is_super or request.user.can_import_topics):
        messages.error(request, 'ليس لديك صلاحية لاستيراد المواضيع.')
        return redirect('/dashboard/')

    session = get_object_or_404(CouncilSession, pk=session_pk)

    # Check session state (cannot import if frozen)
    if session.status == 'frozen':
        messages.error(request, 'لا يمكن استيراد أو تعديل مواضيع جلسة مؤرشفة ومجمدة.')
        return redirect('council:session_detail', pk=session_pk)

    action = request.POST.get('action', '')

    # ── Action: Cancel Preview ───────────────────────────────────────────────
    if request.method == 'POST' and action == 'cancel_preview':
        request.session.pop(f'word_import_topics_{session_pk}', None)
        request.session.pop(f'word_import_filename_{session_pk}', None)
        return redirect('council:import_word', session_pk=session_pk)

    # ── Action: Confirm Import (Selected Topics) ──────────────────────────────
    if request.method == 'POST' and action == 'confirm_import':
        topics_cache = request.session.get(f'word_import_topics_{session_pk}')
        if not topics_cache:
            messages.error(request, 'انتهت صلاحية جلسة المعاينة، يرجى إعادة رفع الملف.')
            return redirect('council:import_word', session_pk=session_pk)

        selected_indices = request.POST.getlist('selected_topics')
        if not selected_indices:
            messages.error(request, 'يرجى تحديد موضوع واحد على الأقل للاستيراد.')
            context = {
                'session': session,
                'page_title': 'معاينة واستيراد مواضيع من Word',
                'step': 'preview',
                'topics': topics_cache,
                'total_topics': len(topics_cache),
                'filename': request.session.get(f'word_import_filename_{session_pk}', 'المحضر.docx'),
                'existing_topics_count': session.topics.count(),
            }
            return render(request, 'council/import_word.html', context)

        selected_set = set(str(idx) for idx in selected_indices)
        selected_topics = [t for i, t in enumerate(topics_cache) if str(i) in selected_set or str(t.get('index')) in selected_set]

        if not selected_topics:
            messages.error(request, 'لم يتم العثور على المواضيع المحددة.')
            return redirect('council:import_word', session_pk=session_pk)

        # Optional: Replace existing topics
        replace_existing = request.POST.get('replace_existing') == '1'
        if replace_existing:
            session.topics.all().delete()

        # Determine starting order_number
        last_order = session.topics.order_by('-order_number').values_list('order_number', flat=True).first() or 0

        created_count = 0
        from django.db import transaction
        with transaction.atomic():
            for idx, data in enumerate(selected_topics, start=1):
                title = data.get('title', '').strip()
                if not title:
                    continue
                Topic.objects.create(
                    session=session,
                    category=data.get('category', 'general'),
                    order_number=last_order + idx,
                    title=title,
                    background=data.get('background', '').strip(),
                    priorities=data.get('priorities', '').strip(),
                    mentioned_persons=data.get('mentioned_persons', ''),
                    created_by=request.user,
                )
                created_count += 1

        # Clean session cache
        request.session.pop(f'word_import_topics_{session_pk}', None)
        request.session.pop(f'word_import_filename_{session_pk}', None)

        if created_count == len(topics_cache):
            messages.success(request, f'تم بنجاح استيراد جميع المواضيع المكتشفة ({created_count} موضوعاً) إلى الجلسة.')
        else:
            messages.success(request, f'تم بنجاح استيراد {created_count} موضوعاً محدداً من أصل {len(topics_cache)} موضوعاً إلى الجلسة.')

        return redirect('council:session_detail', pk=session_pk)

    # ── Action: File Upload & Parse ──────────────────────────────────────────
    if request.method == 'POST':
        uploaded_file = request.FILES.get('word_file')
        if not uploaded_file:
            messages.error(request, 'يرجى اختيار ملف Word للاستيراد.')
            return redirect('council:import_word', session_pk=session_pk)

        name = uploaded_file.name.lower()
        if not (name.endswith('.docx') or name.endswith('.doc')):
            messages.error(request, 'يجب أن يكون الملف بصيغة .docx أو .doc')
            return redirect('council:import_word', session_pk=session_pk)

        try:
            topics_data = parse_word_file(uploaded_file)
        except Exception as exc:
            messages.error(request, f'خطأ في قراءة ملف Word: {exc}')
            return redirect('council:import_word', session_pk=session_pk)

        if not topics_data:
            messages.warning(request, 'لم يتم العثور على أي مواضيع صالحة في الملف المرفوع.')
            return redirect('council:import_word', session_pk=session_pk)

        # Store in session for interactive selection
        request.session[f'word_import_topics_{session_pk}'] = topics_data
        request.session[f'word_import_filename_{session_pk}'] = uploaded_file.name

        context = {
            'session': session,
            'page_title': 'معاينة واستيراد مواضيع من Word',
            'step': 'preview',
            'topics': topics_data,
            'total_topics': len(topics_data),
            'filename': uploaded_file.name,
            'existing_topics_count': session.topics.count(),
        }
        return render(request, 'council/import_word.html', context)

    # ── GET: Check if preview already in session or show upload ──────────────
    cached_topics = request.session.get(f'word_import_topics_{session_pk}')
    if cached_topics and request.GET.get('reset') != '1':
        context = {
            'session': session,
            'page_title': 'معاينة واستيراد مواضيع من Word',
            'step': 'preview',
            'topics': cached_topics,
            'total_topics': len(cached_topics),
            'filename': request.session.get(f'word_import_filename_{session_pk}', 'المحضر.docx'),
            'existing_topics_count': session.topics.count(),
        }
        return render(request, 'council/import_word.html', context)

    # Default Upload Screen
    context = {
        'session': session,
        'page_title': 'استيراد مواضيع من Word',
        'step': 'upload',
        'existing_topics_count': session.topics.count(),
    }
    return render(request, 'council/import_word.html', context)


# ══════════════════════════════════════════════════════════════════════════════
# Agenda Prepare – AJAX API Endpoints (الشاشة الموحدة لإعداد جدول الأعمال)
# ══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/login/')
@require_POST
def api_agenda_topic_add(request, session_pk):
    """
    AJAX: إضافة موضوع جديد من شاشة إعداد جدول الأعمال.
    تتطلب صلاحية can_add_topic أو can_prepare_agenda. الجلسة يجب أن تكون في مرحلة draft.
    """
    if not (request.user.is_super or request.user.can_add_topic or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية لإضافة مواضيع.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)
    if session.status != 'draft':
        return JsonResponse({'success': False, 'error': 'لا يمكن إضافة مواضيع إلا في مرحلة التحضير.'}, status=400)

    form = TopicForm(request.POST, session=session)
    if form.is_valid():
        topic = form.save(commit=False)
        topic.session    = session
        topic.created_by = request.user

        # حساب الترتيب الفرعي بدقة داخل التبويب
        last_in_cat = Topic.objects.filter(session=session, category=topic.category).order_by('-sub_order').first()
        topic.sub_order = (last_in_cat.sub_order + 1) if last_in_cat else 1

        # ضبط الترتيب العام
        if not topic.order_number or topic.order_number >= 999:
            last_topic = Topic.objects.filter(session=session).order_by('-order_number').first()
            topic.order_number = (last_topic.order_number + 1) if last_topic else 1

        topic.save()

        # رفع أوليات الموضوع إن وُجدت مع طلب الحفظ
        uploaded_files = request.FILES.getlist('attachments')
        for f in uploaded_files:
            TopicAttachment.objects.create(
                topic=topic,
                file=f,
                file_name=f.name,
                file_size=f.size,
                file_type=os.path.splitext(f.name)[1].lstrip('.').lower(),
                uploaded_by=request.user
            )

        # إنشاء جدول بيانات فوري إن طُلب مع كامل هيكله وقوالبه وصفوفه
        table_type = request.POST.get('table_type', 'custom')
        table_title = request.POST.get('table_title', '').strip()
        table_headers_raw = request.POST.get('table_headers_json', '').strip()
        table_rows_raw = request.POST.get('table_rows_json', '').strip()
        table_sum_cols_raw = request.POST.get('table_sum_cols_json', '').strip()
        table_notes = request.POST.get('table_notes', '').strip()
        create_table = (request.POST.get('create_table') == '1') or bool(table_title) or bool(table_rows_raw and table_rows_raw != '[]')

        if create_table:
            from council.models import TopicTable, TABLE_PRESET_CHOICES
            from council.views.table_views import PRESET_HEADERS_MAP, PRESET_SUM_COLS_MAP

            headers = []
            if table_headers_raw:
                try:
                    parsed_h = json.loads(table_headers_raw)
                    if isinstance(parsed_h, list):
                        headers = [str(h).strip() for h in parsed_h if str(h).strip()]
                except Exception:
                    pass
            if not headers:
                headers = PRESET_HEADERS_MAP.get(table_type, ['م', 'البيان', 'ملاحظات'])

            rows_data = []
            if table_rows_raw:
                try:
                    parsed_r = json.loads(table_rows_raw)
                    if isinstance(parsed_r, list):
                        for r in parsed_r:
                            if isinstance(r, list):
                                rows_data.append([str(c) if c is not None else '' for c in r])
                except Exception:
                    pass

            sum_columns = []
            if table_sum_cols_raw:
                try:
                    parsed_s = json.loads(table_sum_cols_raw)
                    if isinstance(parsed_s, list):
                        for c in parsed_s:
                            if str(c).isdigit():
                                sum_columns.append(int(c))
                except Exception:
                    pass
            elif table_type in PRESET_SUM_COLS_MAP:
                sum_columns = PRESET_SUM_COLS_MAP[table_type]

            default_title = dict(TABLE_PRESET_CHOICES).get(table_type, 'جدول الموضوع')
            TopicTable.objects.create(
                topic=topic,
                table_type=table_type,
                title=table_title or default_title,
                headers=headers,
                rows_data=rows_data,
                sum_columns=sum_columns,
                order=1,
                notes=table_notes
            )

        first_tbl = topic.tables.first()
        tbl_url = f'/tables/{first_tbl.pk}/edit/?next=prepare' if first_tbl else f'/topics/{topic.pk}/tables/new/?next=prepare'

        return JsonResponse({
            'success':     True,
            'topic_id':    topic.pk,
            'title':       topic.title,
            'category':    topic.category,
            'sub_order':   topic.sub_order,
            'order_number': topic.order_number,
            'has_priorities': bool(topic.priorities),
            'attachments_count': topic.attachments.count(),
            'tables_count': topic.tables.count(),
            'edit_url':    f'/topics/{topic.pk}/edit/',
            'delete_url':  f'/api/agenda/topics/{topic.pk}/delete/',
            'attach_url':  f'/api/agenda/topics/{topic.pk}/attachments/',
            'table_url':   tbl_url,
        })
    return JsonResponse({'success': False, 'errors': form.errors}, status=400)


@login_required(login_url='/login/')
@require_POST
def api_agenda_category_add(request, session_pk):
    """
    AJAX: إضافة عنوان رئيسي جديد أو استرجاع عنوان رسمي تم استبعاده.
    """
    if not (request.user.is_super or request.user.can_add_topic or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية لإدارة العناوين الرئيسية.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)
    if session.status != 'draft':
        return JsonResponse({'success': False, 'error': 'لا يمكن التعديل إلا في مرحلة التحضير.'}, status=400)

    restore_key = request.POST.get('restore_key', '').strip()
    if restore_key:
        ok, res = session.restore_standard_category(restore_key)
        if not ok:
            return JsonResponse({'success': False, 'error': res}, status=400)
        return JsonResponse({'success': True, 'key': restore_key, 'label': res, 'is_restored': True})

    label = request.POST.get('label', '').strip()
    if not label:
        return JsonResponse({'success': False, 'error': 'يرجى كتابة اسم العنوان الرئيسي أو اختيار عنوان لاسترجاعه.'}, status=400)

    key, clean_label = session.add_custom_category(label)
    return JsonResponse({'success': True, 'key': key, 'label': clean_label, 'is_restored': False})


@login_required(login_url='/login/')
@require_POST
def api_agenda_category_delete(request, session_pk):
    """
    AJAX: استبعاد عنوان رئيسي من جدول أعمال الجلسة إذا لم تكن به مواضيع.
    """
    if not (request.user.is_super or request.user.can_delete_topic or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية لاستبعاد عناوين رئيسية.'}, status=403)

    session = get_object_or_404(CouncilSession, pk=session_pk)
    if session.status != 'draft':
        return JsonResponse({'success': False, 'error': 'لا يمكن التعديل إلا في مرحلة التحضير.'}, status=400)

    key = request.POST.get('category_key', '').strip()
    if not key:
        return JsonResponse({'success': False, 'error': 'رمز العنوان غير محدد.'}, status=400)

    ok, msg = session.remove_agenda_category(key)
    if not ok:
        return JsonResponse({'success': False, 'error': msg}, status=400)
    return JsonResponse({'success': True, 'message': msg, 'key': key})


@login_required(login_url='/login/')
def api_agenda_topic_get(request, pk):
    """
    AJAX: جلب بيانات الموضوع بصيغة JSON نقية لتعبئة نافذة التعديل السريع فورياً.
    """
    if not (request.user.is_super or request.user.can_edit_topic or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'غير مصرح.'}, status=403)

    topic = get_object_or_404(Topic.objects.select_related('session'), pk=pk)
    return JsonResponse({
        'success': True,
        'topic': {
            'id': topic.pk,
            'title': topic.title,
            'category': topic.category,
            'memo_number': topic.memo_number or '',
            'memo_date': topic.memo_date or '',
            'presenting_entity': topic.presenting_entity or '',
            'mentioned_persons': topic.mentioned_persons or '',
            'background': topic.background or '',
            'priorities': topic.priorities or '',
            'order_number': topic.order_number,
            'sub_order': topic.sub_order,
        }
    })


@login_required(login_url='/login/')
@require_POST
def api_agenda_topic_update(request, pk):
    """
    AJAX: تعديل موضوع من شاشة إعداد جدول الأعمال مع إرجاع كامل الحقول المحدثة.
    """
    if not (request.user.is_super or request.user.can_edit_topic or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية لتعديل المواضيع.'}, status=403)

    topic = get_object_or_404(Topic.objects.select_related('session'), pk=pk)
    if topic.session.status != 'draft':
        return JsonResponse({'success': False, 'error': 'لا يمكن التعديل إلا في مرحلة التحضير.'}, status=400)

    form = TopicForm(request.POST, instance=topic, session=topic.session)
    if form.is_valid():
        topic = form.save()
        return JsonResponse({
            'success':           True,
            'topic_id':          topic.pk,
            'title':             topic.title,
            'category':          topic.category,
            'memo_number':       topic.memo_number or '',
            'memo_date':         topic.memo_date or '',
            'presenting_entity': topic.presenting_entity or '',
            'sub_order':         topic.sub_order,
            'has_priorities':    bool(topic.priorities),
        })
    return JsonResponse({'success': False, 'errors': form.errors}, status=400)


@login_required(login_url='/login/')
def api_agenda_topic_table_get(request, pk):
    """
    AJAX: جلب جدول بيانات الموضوع لعرضه وتحريره في شاشة فلاشية داخلية دون مغادرة الصفحة.
    """
    if not (request.user.is_super or request.user.can_add_table or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'غير مصرح.'}, status=403)

    topic = get_object_or_404(Topic.objects.select_related('session').prefetch_related('tables'), pk=pk)
    table = topic.tables.first()
    if not table:
        return JsonResponse({
            'success': True,
            'has_table': False,
            'topic_title': topic.title,
        })

    return JsonResponse({
        'success': True,
        'has_table': True,
        'table_id': table.pk,
        'table_type': table.table_type,
        'title': table.title,
        'headers': table.headers,
        'rows_data': table.rows_data,
        'sum_columns': table.sum_columns,
        'notes': table.notes or '',
        'topic_title': topic.title,
    })


@login_required(login_url='/login/')
@require_POST
def api_agenda_topic_table_save(request, pk):
    """
    AJAX: حفظ أو تعديل جدول بيانات الموضوع مباشرة داخل نفس الشاشة الفلاشية.
    """
    if not (request.user.is_super or request.user.can_add_table or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية لإدارة الجداول.'}, status=403)

    topic = get_object_or_404(Topic.objects.select_related('session').prefetch_related('tables'), pk=pk)
    if topic.session.status != 'draft':
        return JsonResponse({'success': False, 'error': 'لا يمكن التعديل إلا في مرحلة التحضير.'}, status=400)

    from council.models import TopicTable, TABLE_PRESET_CHOICES
    from council.views.table_views import PRESET_HEADERS_MAP, PRESET_SUM_COLS_MAP

    table_type = request.POST.get('table_type', 'custom')
    table_title = request.POST.get('table_title', '').strip()
    table_headers_raw = request.POST.get('table_headers_json', '').strip()
    table_rows_raw = request.POST.get('table_rows_json', '').strip()
    table_sum_cols_raw = request.POST.get('table_sum_cols_json', '').strip()
    table_notes = request.POST.get('table_notes', '').strip()

    headers = []
    if table_headers_raw:
        try:
            parsed_h = json.loads(table_headers_raw)
            if isinstance(parsed_h, list):
                headers = [str(h).strip() for h in parsed_h if str(h).strip()]
        except Exception:
            pass
    if not headers:
        headers = PRESET_HEADERS_MAP.get(table_type, ['م', 'البيان', 'ملاحظات'])

    rows_data = []
    if table_rows_raw:
        try:
            parsed_r = json.loads(table_rows_raw)
            if isinstance(parsed_r, list):
                for r in parsed_r:
                    if isinstance(r, list):
                        rows_data.append([str(c) if c is not None else '' for c in r])
        except Exception:
            pass

    sum_columns = []
    if table_sum_cols_raw:
        try:
            parsed_s = json.loads(table_sum_cols_raw)
            if isinstance(parsed_s, list):
                for c in parsed_s:
                    if str(c).isdigit():
                        sum_columns.append(int(c))
        except Exception:
            pass
    elif table_type in PRESET_SUM_COLS_MAP:
        sum_columns = PRESET_SUM_COLS_MAP[table_type]

    default_title = dict(TABLE_PRESET_CHOICES).get(table_type, 'جدول الموضوع')
    final_title = table_title or default_title

    table = topic.tables.first()
    if table:
        table.table_type = table_type
        table.title = final_title
        table.headers = headers
        table.rows_data = rows_data
        table.sum_columns = sum_columns
        table.notes = table_notes
        table.save()
    else:
        table = TopicTable.objects.create(
            topic=topic,
            table_type=table_type,
            title=final_title,
            headers=headers,
            rows_data=rows_data,
            sum_columns=sum_columns,
            order=1,
            notes=table_notes
        )

    return JsonResponse({
        'success':      True,
        'table_id':     table.pk,
        'title':        table.title,
        'rows_count':   len(table.rows_data),
        'cols_count':   len(table.headers),
        'tables_count': topic.tables.count(),
    })


@login_required(login_url='/login/')
@require_POST
def api_agenda_topic_delete(request, pk):
    """
    AJAX: حذف موضوع من شاشة إعداد جدول الأعمال.
    تتطلب صلاحية can_delete_topic أو can_prepare_agenda. الجلسة يجب أن تكون draft.
    """
    if not (request.user.is_super or request.user.can_delete_topic or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية لحذف المواضيع.'}, status=403)

    topic = get_object_or_404(Topic.objects.select_related('session'), pk=pk)
    if topic.session.status != 'draft':
        return JsonResponse({'success': False, 'error': 'لا يمكن الحذف إلا في مرحلة التحضير.'}, status=400)

    title    = topic.title
    category = topic.category
    topic.delete()
    return JsonResponse({'success': True, 'title': title, 'category': category})


@login_required(login_url='/login/')
def api_agenda_topic_attachments(request, pk):
    """
    AJAX GET: قائمة مرفقات الموضوع.
    AJAX POST (multipart): رفع مرفق جديد (أوليات الموضوع).
    تتطلب صلاحية can_upload_attachments أو can_prepare_agenda. الجلسة يجب أن تكون draft.
    """
    topic = get_object_or_404(Topic.objects.select_related('session').prefetch_related('attachments'), pk=pk)

    if request.method == 'GET':
        if not (request.user.is_super or request.user.can_view_attachments or request.user.can_upload_attachments or getattr(request.user, 'can_prepare_agenda', False)):
            return JsonResponse({'success': False, 'error': 'غير مصرح.'}, status=403)
        attachments = [
            {
                'id':        a.pk,
                'name':      a.file_name,
                'url':       a.file.url if a.file else '',
                'uploaded_at': a.uploaded_at.strftime('%Y-%m-%d %H:%M') if hasattr(a, 'uploaded_at') else '',
                'delete_url': f'/api/agenda/attachments/{a.pk}/delete/',
            }
            for a in topic.attachments.all()
        ]
        return JsonResponse({'success': True, 'attachments': attachments})

    # POST – upload
    if not (request.user.is_super or request.user.can_upload_attachments or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية لرفع المرفقات.'}, status=403)
    if topic.session.status != 'draft':
        return JsonResponse({'success': False, 'error': 'لا يمكن رفع الأوليات إلا في مرحلة التحضير.'}, status=400)

    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        attachment = form.save(commit=False)
        attachment.topic       = topic
        attachment.uploaded_by = request.user
        if request.FILES.get('file'):
            attachment.file_name = request.FILES['file'].name
        attachment.save()
        return JsonResponse({
            'success': True,
            'id':      attachment.pk,
            'name':    attachment.file_name,
            'url':     attachment.file.url if attachment.file else '',
            'delete_url': f'/api/agenda/attachments/{attachment.pk}/delete/',
        })
    return JsonResponse({'success': False, 'errors': form.errors}, status=400)


@login_required(login_url='/login/')
@require_POST
def api_agenda_attachment_delete(request, pk):
    """
    AJAX: حذف مرفق من شاشة إعداد جدول الأعمال.
    تتطلب صلاحية can_delete_attachments أو can_prepare_agenda. الجلسة يجب أن تكون draft.
    """
    if not (request.user.is_super or request.user.can_delete_attachments or getattr(request.user, 'can_prepare_agenda', False)):
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية لحذف المرفقات.'}, status=403)

    attachment = get_object_or_404(
        TopicAttachment.objects.select_related('topic__session'), pk=pk
    )
    if attachment.topic.session.status != 'draft':
        return JsonResponse({'success': False, 'error': 'لا يمكن الحذف إلا في مرحلة التحضير.'}, status=400)

    name = attachment.file_name
    # Remove physical file if exists
    if attachment.file:
        try:
            if os.path.isfile(attachment.file.path):
                os.remove(attachment.file.path)
        except Exception:
            pass
    attachment.delete()
    return JsonResponse({'success': True, 'name': name})

