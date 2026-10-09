"""
Export Views
University Council Management System

Exports session minutes as a professional Arabic RTL Word document.
"""
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect

from council.models import CouncilSession
from council.services.word_export import generate_session_minutes


# ── Export Session as Word ─────────────────────────────────────────────────────

@login_required(login_url='/login/')
def export_session_word_view(request, pk):
    """
    Export a complete session's minutes as a .docx Word document.
    Includes: session header, attendance table, grouped topics with
    vote summaries and decisions.
    Requires can_export_minutes permission.
    """
    if not (request.user.is_super or request.user.can_export_minutes):
        messages.error(request, 'ليس لديك صلاحية لتصدير المحاضر الرسمية.')
        return redirect('/dashboard/')

    session = get_object_or_404(
        CouncilSession.objects.select_related('created_by'),
        pk=pk
    )
    if not session.can_be_seen_by(request.user):
        messages.error(request, 'هذه الجلسة في مرحلة التحضير ولا يمكن تصدير محضرها حالياً.')
        return redirect('/dashboard/')

    # Generate document bytes
    docx_buffer = generate_session_minutes(session)

    # Build a safe ASCII-compatible filename
    safe_number = str(session.session_number)
    safe_date   = str(session.date)
    filename    = f'session_{safe_number}_{safe_date}.docx'

    response = HttpResponse(
        docx_buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    # Use RFC 5987 encoding for the Content-Disposition header
    response['Content-Disposition'] = (
        f'attachment; filename="{filename}"; '
        f"filename*=UTF-8''%D9%85%D8%AD%D8%B6%D8%B1_%D8%AC%D9%84%D8%B3%D8%A9_{safe_number}.docx"
    )
    return response
