"""
Decision Views
University Council Management System

Handles: create/edit decision for a topic, delete decision.
Requires can_draft permission.
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from council.models import Topic, Decision
from council.forms.topic_forms import DecisionForm


# ── Create / Edit Decision ─────────────────────────────────────────────────────

@login_required(login_url='/login/')
def decision_create_edit_view(request, topic_pk):
    """
    Create a new decision or edit the existing one for a topic.
    Requires can_draft_decision.

    If the topic already has a Decision object, this acts as an edit form.
    If not, it creates a new one.
    """
    if not (request.user.is_super or request.user.can_draft_decision):
        messages.error(request, 'ليس لديك صلاحية لصياغة القرارات.')
        return redirect('/dashboard/')

    topic = get_object_or_404(
        Topic.objects.select_related('session'),
        pk=topic_pk
    )

    # Retrieve existing decision or None
    existing_decision = topic.decision if topic.has_decision() else None
    is_edit = existing_decision is not None

    if request.method == 'POST':
        form = DecisionForm(request.POST, instance=existing_decision)
        if form.is_valid():
            decision = form.save(commit=False)
            decision.topic = topic
            # Only set drafted_by on first creation
            if not is_edit:
                decision.drafted_by = request.user
            decision.save()

            action_label = 'تحديث' if is_edit else 'إنشاء'
            messages.success(request, f'تم {action_label} القرار بنجاح.')
            return redirect('council:topic_detail', pk=topic.pk)
    else:
        form = DecisionForm(instance=existing_decision)
        # Pre-populate from AI suggestion if available and no existing text
        if existing_decision and existing_decision.ai_suggested_text and not existing_decision.decision_text:
            form.initial['decision_text'] = existing_decision.ai_suggested_text

    context = {
        'form':              form,
        'topic':             topic,
        'session':           topic.session,
        'existing_decision': existing_decision,
        'is_edit':           is_edit,
        'page_title':        'تعديل القرار' if is_edit else 'صياغة قرار جديد',
    }
    return render(request, 'council/decision_form.html', context)


# ── Delete Decision ────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
@require_POST
def decision_delete_view(request, topic_pk):
    """
    Delete the decision for a topic (POST only).
    Requires can_delete_decision.
    """
    if not (request.user.is_super or request.user.can_delete_decision):
        messages.error(request, 'ليس لديك صلاحية لحذف القرارات.')
        return redirect('/dashboard/')

    topic = get_object_or_404(Topic.objects.select_related('session'), pk=topic_pk)

    if topic.has_decision():
        topic.decision.delete()
        messages.success(request, 'تم حذف القرار بنجاح.')
    else:
        messages.warning(request, 'لا يوجد قرار لهذا الموضوع.')

    return redirect('council:topic_detail', pk=topic_pk)
