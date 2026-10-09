# -*- coding: utf-8 -*-
"""
Views and API controllers for the Council Smart Audio Reader (المقترح م7).
Provides:
  - api_smart_reader_data: structured text chunks with DOM mappings
  - api_smart_reader_synthesize: neural MP3 synthesis with local fallback
  - api_smart_reader_log: audit usage logging
  - smart_reader_settings_view: configuration dashboard
"""
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.contrib import messages

from council.models import CouncilSession, Topic, SmartReaderSetting, SmartReaderLog
from council.services.smart_reader_service import (
    extract_topic_smart_text,
    extract_session_smart_text,
    synthesize_neural_chunk_sync
)

def check_smart_reader_permission(user):
    """Check if user has permission to operate the Smart Audio Reader."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_super', False):
        return True
    return bool(getattr(user, 'can_use_smart_reader', False))


@login_required(login_url='/login/')
@require_GET
def api_smart_reader_data(request):
    """
    Returns verbatim text chunks for a Topic or Session ready for synchronized
    speech synthesis and DOM visual highlighting.
    """
    if not check_smart_reader_permission(request.user):
        return JsonResponse({'success': False, 'error': 'غير مخوّل باستخدام القراءة الذكية'}, status=403)

    topic_id = request.GET.get('topic_id')
    session_id = request.GET.get('session_id')

    setting = SmartReaderSetting.get_settings()

    if topic_id:
        topic = get_object_or_404(Topic, id=topic_id)
        data = extract_topic_smart_text(topic)
    elif session_id:
        session = get_object_or_404(CouncilSession, id=session_id)
        data = extract_session_smart_text(session)
    else:
        return JsonResponse({'success': False, 'error': 'يرجى تحديد معرف الجلسة أو الموضوع'}, status=400)

    data['success'] = True
    data['settings'] = {
        'voice_mode': setting.voice_mode,
        'neural_voice': setting.neural_voice,
        'default_speed': setting.default_speed,
        'auto_scroll': setting.auto_scroll,
        'highlight_color': setting.highlight_color,
    }
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


@login_required(login_url='/login/')
@require_POST
def api_smart_reader_synthesize(request):
    """
    Synthesize an individual Arabic text chunk using Cloud Neural TTS (edge-tts).
    If synthesis succeeds, returns audio_url.
    If synthesis fails or times out, returns fallback_to_local=True so the frontend
    gracefully uses the browser's Web Speech API.
    """
    if not check_smart_reader_permission(request.user):
        return JsonResponse({'success': False, 'error': 'غير مخوّل'}, status=403)

    try:
        payload = json.loads(request.body) if request.body else {}
    except Exception:
        payload = {}

    text = payload.get('text', '').strip()
    if not text:
        text = request.POST.get('text', '').strip()

    if not text:
        return JsonResponse({'success': False, 'error': 'لا يوجد نص للقراءة'}, status=400)

    setting = SmartReaderSetting.get_settings()
    voice = payload.get('voice') or request.POST.get('voice') or setting.neural_voice or 'ar-SA-HamedNeural'
    
    try:
        speed = float(payload.get('speed') or request.POST.get('speed') or setting.default_speed or 1.0)
    except (ValueError, TypeError):
        speed = 1.0

    audio_url = synthesize_neural_chunk_sync(text, voice=voice, speed=speed)

    if audio_url:
        return JsonResponse({
            'success': True,
            'audio_url': audio_url,
            'voice': voice,
            'speed': speed,
            'mode': 'cloud_neural'
        })
    else:
        # Graceful fallback indicator
        return JsonResponse({
            'success': True,
            'audio_url': '',
            'fallback_to_local': True,
            'mode': 'browser_local',
            'message': 'استخدام الصوت المحلي التلقائي'
        })


@login_required(login_url='/login/')
@require_POST
def api_smart_reader_log(request):
    """
    Record an audit entry when a council member or operator plays the Smart Reader.
    """
    if not check_smart_reader_permission(request.user):
        return JsonResponse({'success': False}, status=403)

    try:
        payload = json.loads(request.body) if request.body else {}
    except Exception:
        payload = {}

    session_id = payload.get('session_id') or request.POST.get('session_id')
    topic_id = payload.get('topic_id') or request.POST.get('topic_id')
    target_title = payload.get('target_title') or request.POST.get('target_title') or 'قراءة ذكية'
    voice_mode = payload.get('voice_mode') or request.POST.get('voice_mode') or 'cloud_neural'
    
    try:
        speed = float(payload.get('speed') or request.POST.get('speed') or 1.0)
    except Exception:
        speed = 1.0
        
    try:
        chunks_count = int(payload.get('chunks_count') or request.POST.get('chunks_count') or 0)
    except Exception:
        chunks_count = 0

    session = CouncilSession.objects.filter(id=session_id).first() if session_id else None
    topic = Topic.objects.filter(id=topic_id).first() if topic_id else None

    SmartReaderLog.objects.create(
        user=request.user,
        session=session,
        topic=topic,
        target_title=target_title[:300],
        voice_mode=voice_mode[:30],
        speed=speed,
        chunks_count=chunks_count
    )

    return JsonResponse({'success': True})


@login_required(login_url='/login/')
def smart_reader_settings_view(request):
    """
    Administrative management view for Smart Audio Reader settings and usage log.
    Requires can_manage_smart_reader.
    """
    if not (request.user.is_super or getattr(request.user, 'can_manage_smart_reader', False)):
        messages.error(request, 'غير مصرح لك بإدارة إعدادات القراءة الذكية.')
        return redirect('/dashboard/')

    setting = SmartReaderSetting.get_settings()
    recent_logs = SmartReaderLog.objects.select_related('user', 'session', 'topic').order_by('-created_at')[:30]

    if request.method == 'POST':
        setting.voice_mode = request.POST.get('voice_mode', 'cloud_neural')
        setting.neural_voice = request.POST.get('neural_voice', 'ar-SA-HamedNeural')
        try:
            setting.default_speed = float(request.POST.get('default_speed', 1.0))
        except ValueError:
            setting.default_speed = 1.0
        setting.auto_scroll = request.POST.get('auto_scroll') == 'on'
        setting.highlight_color = request.POST.get('highlight_color', '#FEF08A')
        setting.updated_by = request.user
        setting.save()

        messages.success(request, 'تم حفظ إعدادات القراءة الذكية بنجاح.')
        return redirect('council:smart_reader_settings')

    context = {
        'setting': setting,
        'recent_logs': recent_logs,
        'title': 'إعدادات وسجل القراءة الذكية للمجلس',
    }
    return render(request, 'council/smart_reader_settings.html', context)
