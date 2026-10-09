"""
Vote Views
University Council Management System

Handles: submit/update vote (AJAX JSON), view vote results (JSON).
"""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from council.models import Topic, Vote, VOTE_CHOICES
from council.forms.topic_forms import VoteForm


# ── Submit / Update Vote ───────────────────────────────────────────────────────

@login_required(login_url='/login/')
@require_POST
def vote_view(request, topic_pk):
    """
    Submit or update the authenticated user's vote on a topic.
    Requires can_vote permission.
    Accepts:  POST body (application/x-www-form-urlencoded or JSON)
              Fields: choice (approve|reject|reserve), notes (optional)
    Returns:  JSON  { ok, vote_id, choice, choice_label, notes, summary }
    """
    if not (request.user.is_super or request.user.can_vote):
        return JsonResponse(
            {'ok': False, 'error': 'ليس لديك صلاحية للتصويت.'},
            status=403
        )

    topic = get_object_or_404(Topic, pk=topic_pk)

    # Parse request data – support both JSON body and form data
    content_type = request.content_type or ''
    if 'application/json' in content_type:
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'بيانات JSON غير صالحة.'}, status=400)
    else:
        data = request.POST

    form = VoteForm(data)
    if not form.is_valid():
        errors = {field: errs[0] for field, errs in form.errors.items()}
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    choice = form.cleaned_data['choice']
    notes  = form.cleaned_data.get('notes', '')

    # Exit Permit Check (منع التصويت لمن غادر بإذن رسمي)
    from council.models import ExitPermit, TopicDisplayState
    if ExitPermit.objects.filter(session=topic.session, member=request.user, status='approved').exists():
        return JsonResponse({
            'ok': False,
            'error': 'تمت الموافقة على مغادرتك للجلسة مسبقاً، ولا يمكنك التصويت بعد المغادرة.'
        }, status=403)

    # Topic Display State Check (فتح وإغلاق التصويت بيد الرئيس)
    state = getattr(topic, 'display_state', None) or TopicDisplayState.objects.filter(topic=topic).first()
    if state and state.display_status != 'voting':
        return JsonResponse({
            'ok': False,
            'error': 'باب التصويت على هذا الموضوع مغلق حالياً. يُفتح التصويت بإشارة وتوجيه من رئيس المجلس.'
        }, status=403)

    # Single Vote per Seat Check (منع ازدواجية التصويت)
    from council.models import EntitySeat
    from django.db.models import Q
    seat = EntitySeat.objects.filter(
        Q(primary_rep=request.user) | Q(deputy_rep_1=request.user) | Q(deputy_rep_2=request.user),
        is_active=True
    ).first()

    if seat:
        existing_seat_vote = Vote.objects.filter(topic=topic, seat=seat).exclude(member=request.user).first()
        if existing_seat_vote:
            return JsonResponse({
                'ok': False,
                'error': f'تم تسجيل تصويت هذا المقعد ({seat.name}) مسبقاً لهذا الموضوع بواسطة ({existing_seat_vote.member.full_name}). لا يمكن تكرار التصويت لنفس المقعد.'
            }, status=403)

    is_proxy = (seat.primary_rep != request.user) if seat else False

    # update_or_create so the user can change their vote
    vote, created = Vote.objects.update_or_create(
        topic=topic,
        member=request.user,
        defaults={
            'choice': choice,
            'notes': notes,
            'seat': seat,
            'is_proxy': is_proxy,
        },
    )

    summary = topic.get_vote_summary()
    percentages = state.get_vote_percentages() if state else {}

    return JsonResponse({
        'ok':           True,
        'vote_id':      vote.pk,
        'choice':       vote.choice,
        'choice_label': vote.get_choice_display(),
        'choice_icon':  vote.get_choice_icon(),
        'choice_color': vote.get_choice_color(),
        'notes':        vote.notes,
        'created':      created,
        'summary': {
            'total':   summary['total'],
            'approve': summary['approve'],
            'reject':  summary['reject'],
            'reserve': summary['reserve'],
        },
        'percentages':  percentages,
    })


# ── Vote Results ───────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def vote_results_view(request, topic_pk):
    """
    Return vote results for a topic as JSON.
    Requires can_view_vote_details permission.
    GET /council/topics/<pk>/votes/results/
    Returns: {
        ok, topic_id, topic_title, summary,
        votes: [ {member_name, choice, choice_label, choice_icon, notes} ]
    }
    """
    if not (request.user.is_super or request.user.can_view_vote_details):
        return JsonResponse(
            {'ok': False, 'error': 'ليس لديك صلاحية للاطلاع على تفاصيل المصوتين.'},
            status=403
        )

    topic = get_object_or_404(
        Topic.objects.prefetch_related('votes', 'votes__member'),
        pk=topic_pk
    )

    summary = topic.get_vote_summary()

    votes_list = [
        {
            'member_id':    v.member_id,
            'member_name':  v.member.full_name,
            'member_title': v.member.get_title_display(),
            'choice':       v.choice,
            'choice_label': v.get_choice_display(),
            'choice_icon':  v.get_choice_icon(),
            'choice_color': v.get_choice_color(),
            'notes':        v.notes,
            'voted_at':     v.voted_at.strftime('%Y-%m-%d %H:%M'),
        }
        for v in topic.votes.select_related('member').order_by('voted_at')
    ]

    return JsonResponse({
        'ok':          True,
        'topic_id':    topic.pk,
        'topic_title': topic.title,
        'summary':     summary,
        'votes':       votes_list,
    })
