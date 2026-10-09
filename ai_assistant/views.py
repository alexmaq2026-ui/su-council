import json
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.conf import settings

from council.models import Topic, TopicRecording


# ---------------------------------------------------------------------------
# AI Assistant views (Phase 2 stubs – full implementation in Phase 3)
# ---------------------------------------------------------------------------

@login_required(login_url='/login/')
@require_POST
def transcribe_view(request, topic_id):
    """Stub: Transcribe the audio recording attached to a topic.
    Requires can_draft_decision or can_edit_topic.
    """
    if not (request.user.is_super or request.user.can_draft_decision or request.user.can_edit_topic):
        return JsonResponse({'success': False, 'message': 'ليس لديك صلاحية لاستخدام المساعد الذكي.'}, status=403)

    # Validate topic exists
    topic = get_object_or_404(Topic, pk=topic_id)

    # Ensure a recording exists for this topic
    recording = TopicRecording.objects.filter(topic=topic).first()
    if not recording:
        return JsonResponse(
            {
                'success': False,
                'message': 'لا يوجد تسجيل صوتي مرتبط بهذا الموضوع.',
            },
            status=404,
        )

    # Check that the OpenAI API key has been configured
    openai_key = getattr(settings, 'OPENAI_API_KEY', None)
    if not openai_key:
        return JsonResponse(
            {
                'success': False,
                'message': (
                    'مفتاح OpenAI API غير مُهيَّأ. '
                    'يرجى إضافة OPENAI_API_KEY إلى ملف الإعدادات.'
                ),
            },
            status=503,
        )

    # --- Phase 3 placeholder ---
    return JsonResponse(
        {
            'success': True,
            'message': 'الميزة ستكون متاحة قريباً',
            'topic_id': topic_id,
            'recording_id': recording.pk,
        }
    )


@login_required(login_url='/login/')
@require_POST
def analyze_view(request, topic_id):
    """Stub: AI-powered analysis of a topic's discussion text.
    Requires can_draft_decision or can_edit_topic.
    """
    if not (request.user.is_super or request.user.can_draft_decision or request.user.can_edit_topic):
        return JsonResponse({'success': False, 'message': 'ليس لديك صلاحية لاستخدام المساعد الذكي.'}, status=403)

    # Validate topic exists
    topic = get_object_or_404(Topic, pk=topic_id)

    # Assemble the discussion text that would be sent to the AI
    discussion_parts = []
    if topic.background:
        discussion_parts.append(f'الخلفية:\n{topic.background}')
    if topic.priorities:
        discussion_parts.append(f'الأولويات:\n{topic.priorities}')
    if topic.mentioned_persons:
        discussion_parts.append(f'الأشخاص المذكورون:\n{topic.mentioned_persons}')

    # Include any existing transcription from recordings
    recordings = TopicRecording.objects.filter(topic=topic)
    for rec in recordings:
        if rec.transcription_text:
            discussion_parts.append(f'النص المنقول:\n{rec.transcription_text}')

    if not discussion_parts:
        return JsonResponse(
            {
                'success': False,
                'message': 'لا يوجد نص كافٍ لتحليله لهذا الموضوع.',
            },
            status=400,
        )

    # --- Phase 3 placeholder ---
    return JsonResponse(
        {
            'success': True,
            'message': 'تحليل الذكاء الاصطناعي سيكون متاحاً في المرحلة القادمة',
            'topic_id': topic_id,
            'topic_title': topic.title,
            'text_length': sum(len(p) for p in discussion_parts),
        }
    )
