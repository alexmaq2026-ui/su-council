# -*- coding: utf-8 -*-
"""
Smart Audio Reader & Neural TTS Service (المقترح م7)
Handles verbatim text extraction (كما ورد بلا تلخيص), chunking,
and Neural audio synthesis with local Web Speech fallback.
"""
import os
import re
import hashlib
import asyncio
from django.conf import settings
from council.models import CouncilSession, Topic, Decision, Attendance, SmartReaderSetting, SmartReaderLog

CACHE_DIR = os.path.join(settings.MEDIA_ROOT, 'smart_reader_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

def split_arabic_sentences(text: str, max_chars: int = 220) -> list:
    """
    Split Arabic text into coherent, natural sentences for speech synthesis
    and synchronized visual highlighting.
    """
    if not text:
        return []
    
    # Clean whitespace and strip
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []

    # Regex to split on sentence terminators: newline, dot, semicolon, colon
    raw_parts = re.split(r'([.\n؛!؟]+)', text)
    sentences = []
    current = ""

    for i in range(0, len(raw_parts), 2):
        chunk = raw_parts[i].strip()
        sep = raw_parts[i+1] if i + 1 < len(raw_parts) else ""
        combined = (chunk + sep).strip()
        if not combined:
            continue
        
        if len(current) + len(combined) <= max_chars:
            current = (current + " " + combined).strip()
        else:
            if current:
                sentences.append(current)
            current = combined

    if current:
        sentences.append(current)

    # Fallback if any single chunk is still overly long
    final_list = []
    for s in sentences:
        if len(s) > max_chars:
            words = s.split(' ')
            sub_chunk = ""
            for w in words:
                if len(sub_chunk) + len(w) + 1 <= max_chars:
                    sub_chunk = (sub_chunk + " " + w).strip()
                else:
                    if sub_chunk:
                        final_list.append(sub_chunk)
                    sub_chunk = w
            if sub_chunk:
                final_list.append(sub_chunk)
        else:
            final_list.append(s)

    return final_list if final_list else [text]


def extract_topic_smart_text(topic: Topic) -> dict:
    """
    Extract exact verbatim text of a topic with full structured metadata.
    Does NOT summarize (كما وردت حرفياً).
    """
    chunks = []
    idx = 0

    # 1. Topic Title & Order
    order_str = f"الموضوع رقم ({topic.order_number})"
    if topic.category:
        order_str += f" ضمن تصنيف {topic.get_category_display()}"
    title_text = f"{order_str}: {topic.title}."
    chunks.append({
        'id': idx,
        'label': 'عنوان الموضوع',
        'text': title_text,
        'field': 'title',
        'is_header': True
    })
    idx += 1

    # 2. Presenting Entity & Memo Details
    details_parts = []
    if topic.presenting_entity:
        details_parts.append(f"الجهة المتقدمة بالموضوع: {topic.presenting_entity}.")
    if topic.memo_number:
        memo_str = f"رقم المذكرة: {topic.memo_number}"
        if topic.memo_date:
            memo_str += f" بتاريخ {topic.memo_date}"
        details_parts.append(memo_str + ".")
    if details_parts:
        chunks.append({
            'id': idx,
            'label': 'بيانات الإحالة والمذكرة',
            'text': " ".join(details_parts),
            'field': 'meta',
            'is_header': False
        })
        idx += 1

    # 3. Background & Context (الحيثيات)
    if topic.background:
        sentences = split_arabic_sentences(topic.background)
        for s in sentences:
            chunks.append({
                'id': idx,
                'label': 'حيثيات الموضوع',
                'text': s,
                'field': 'background',
                'is_header': False
            })
            idx += 1

    # 4. Priorities & Key Requests (الأولويات)
    if topic.priorities:
        sentences = split_arabic_sentences(topic.priorities)
        for s in sentences:
            chunks.append({
                'id': idx,
                'label': 'الأولويات والمطالب',
                'text': s,
                'field': 'priorities',
                'is_header': False
            })
            idx += 1

    # 5. Mentioned Persons (الأشخاص المعنيون)
    if topic.mentioned_persons:
        chunks.append({
            'id': idx,
            'label': 'الأشخاص المعنيون',
            'text': f"الأشخاص المعنيون بهذا الموضوع: {topic.mentioned_persons}.",
            'field': 'mentioned_persons',
            'is_header': False
        })
        idx += 1

    # 6. Official Decision (القرار المعتمد إن وجد)
    decision = getattr(topic, 'decision', None)
    if decision and decision.decision_text:
        chunks.append({
            'id': idx,
            'label': 'قرار مجلس الجامعة',
            'text': f"قرار المجلس: {decision.decision_text}",
            'field': 'decision',
            'is_header': True
        })
        idx += 1

    return {
        'type': 'topic',
        'topic_id': topic.id,
        'title': topic.title,
        'chunks': chunks,
        'total_chunks': len(chunks)
    }


def extract_session_smart_text(session: CouncilSession) -> dict:
    """
    Extract verbatim text of the full council session / previous minutes.
    """
    chunks = []
    idx = 0

    # 1. Preamble & Honors
    p1 = f"محضر مجلس جامعة صنعاء للجلسة رقم ({session.session_number}) للعام الجامعي {session.academic_year}."
    if session.date:
        p1 += f" المنعقدة بتاريخ {session.date}."
    if session.chair_name:
        p1 += f" برئاسة {session.chair_name}."
    chunks.append({
        'id': idx,
        'label': 'ديباجة الجلسة',
        'text': p1,
        'field': 'session_header',
        'is_header': True
    })
    idx += 1

    if session.opening_honors:
        sentences = split_arabic_sentences(session.opening_honors)
        for s in sentences:
            chunks.append({
                'id': idx,
                'label': 'الافتتاح والتكريمات',
                'text': s,
                'field': 'opening_honors',
                'is_header': False
            })
            idx += 1

    # 2. Attendance Summary
    att_qs = Attendance.objects.filter(session=session).select_related('member')
    present_cnt = att_qs.filter(status__in=['present', 'present_primary', 'present_deputy']).count()
    excused_cnt = att_qs.filter(status='excused').count()
    absent_cnt = att_qs.filter(status__in=['unexcused', 'absent']).count()

    att_summary = f"كشف الحضور والنصاب القانوني: حضر الجلسة {present_cnt} عضواً وممثلاً، واعتذر {excused_cnt} عضواً، وغاب دون عذر {absent_cnt} عضواً."
    chunks.append({
        'id': idx,
        'label': 'ملخص النصاب والحضور',
        'text': att_summary,
        'field': 'attendance_summary',
        'is_header': False
    })
    idx += 1

    # 3. Topics & Decisions sequentially
    topics = session.topics.all().order_by('order_number')
    for t in topics:
        chunks.append({
            'id': idx,
            'label': f"الموضوع ({t.order_number})",
            'text': f"الموضوع رقم ({t.order_number}): {t.title}.",
            'field': f'topic_{t.id}_title',
            'is_header': True
        })
        idx += 1

        if t.background:
            s_list = split_arabic_sentences(t.background)
            for s in s_list[:2]: # First 2 sentences of background for session overview
                chunks.append({
                    'id': idx,
                    'label': f"حيثيات الموضوع ({t.order_number})",
                    'text': s,
                    'field': f'topic_{t.id}_background',
                    'is_header': False
                })
                idx += 1

        dec = getattr(t, 'decision', None)
        if dec and dec.decision_text:
            chunks.append({
                'id': idx,
                'label': f"قرار الموضوع ({t.order_number})",
                'text': f"قرار المجلس بشأنه: {dec.decision_text}",
                'field': f'topic_{t.id}_decision',
                'is_header': True
            })
            idx += 1

    return {
        'type': 'session',
        'session_id': session.id,
        'title': f"محضر الجلسة رقم ({session.session_number})",
        'chunks': chunks,
        'total_chunks': len(chunks)
    }


def synthesize_neural_chunk_sync(text: str, voice: str = 'ar-SA-HamedNeural', speed: float = 1.0) -> str:
    """
    Synthesize text to MP3 using edge-tts.
    Returns relative URL or path to the cached MP3 file.
    If synthesis fails, returns empty string so client uses Web Speech fallback.
    """
    if not text or not text.strip():
        return ""

    # Generate unique hash for text + voice + speed
    rate_percent = int(round((speed - 1.0) * 100))
    rate_str = f"{rate_percent:+d}%"

    h = hashlib.sha256(f"{text}_{voice}_{rate_str}".encode('utf-8')).hexdigest()[:24]
    filename = f"tts_{h}.mp3"
    filepath = os.path.join(CACHE_DIR, filename)

    if os.path.exists(filepath) and os.path.getsize(filepath) > 500:
        return f"/media/smart_reader_cache/{filename}"

    # Strict Air-Gap Guard: In isolated mode, avoid external network calls completely
    try:
        from config.isolation import is_isolated
        if is_isolated():
            return ""
    except Exception:
        pass

    # Synthesize via edge_tts in asyncio
    try:
        import edge_tts


        async def _synthesize():
            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            audio_bytes = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]
            return audio_bytes

        # Run async loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # In an already running loop, run in a separate thread or executor
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                audio_bytes = executor.submit(lambda: asyncio.run(_synthesize())).result(timeout=10)
        else:
            audio_bytes = loop.run_until_complete(_synthesize())

        if audio_bytes and len(audio_bytes) > 500:
            with open(filepath, 'wb') as f:
                f.write(audio_bytes)
            return f"/media/smart_reader_cache/{filename}"

    except Exception as e:
        # Fallback to local
        return ""

    return ""
