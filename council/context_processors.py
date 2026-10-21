"""
Council Context Processors - University Council Management System
Provides globally accessible context variables across all templates,
such as detecting currently active live sessions for persistent top banners.
"""
from council.models import CouncilSession, TopicDisplayState


def live_session_context(request):
    """
    Exposes `global_live_session`, `global_active_topic`, and `is_on_live_page`
    to all templates if an active council session is currently in progress.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}

    try:
        import re
        live_match = re.match(r'^/sessions/(\d+)/live/?', request.path)
        if live_match:
            active_session = CouncilSession.objects.filter(pk=int(live_match.group(1)), status='active').first()
        else:
            active_session = None

        if not active_session:
            active_session = CouncilSession.objects.filter(status='active').first()

        if not active_session or active_session.status != 'active' or active_session.is_frozen():
            return {}

        # Verify access permission
        if not (user.is_super or user.can_view_live_session or user.can_start_session_live or active_session.can_be_seen_by(user)):
            return {}

        active_topic_state = TopicDisplayState.objects.filter(
            topic__session_id=active_session.pk,
            display_status__in=['shown', 'voting']
        ).select_related('topic').first()

        active_topic = active_topic_state.topic if active_topic_state else getattr(active_session, 'last_active_topic', None)

        live_url = f'/sessions/{active_session.pk}/live/'
        session_detail_url = f'/sessions/{active_session.pk}/'
        is_on_live_page = request.path.startswith(live_url)
        is_on_active_session_detail = (request.path == session_detail_url or request.path == f'/sessions/{active_session.pk}')

        # Check if currently viewing a topic that belongs to this active session
        is_on_active_session_topic = False
        import re
        topic_match = re.match(r'^/topics/(\d+)/?', request.path)
        if topic_match:
            try:
                from council.models import Topic
                t_id = int(topic_match.group(1))
                is_on_active_session_topic = Topic.objects.filter(pk=t_id, session_id=active_session.pk).exists()
            except Exception:
                pass

        is_controller = bool(user.is_super or user.can_start_session_live)
        has_voting_right = bool(getattr(user, 'can_vote', False))
        is_session_suspended = bool(getattr(active_session, 'is_suspended', False))
        # الوضع الافتراضي: القوة القاهرة معطلة لجميع المستخدمين بما فيهم المدير الأعلى
        # ولا تُطبَّق القوة القاهرة وتجميد الشاشة والتنقل إلا إذا قام المدير الأعلى بتفعيل زر "القوة القاهرة" على هذا العضو تحديداً
        has_force_majeure = bool(getattr(user, 'enforce_force_majeure', False))
        is_member_live_lockdown = bool(is_on_live_page and has_force_majeure and not is_session_suspended)

        return {
            'global_live_session': active_session,
            'global_active_topic': active_topic,
            'is_on_live_page': is_on_live_page,
            'is_on_active_session_detail': is_on_active_session_detail,
            'is_on_active_session_topic': is_on_active_session_topic,
            'is_live_controller': is_controller,
            'is_member_live_lockdown': is_member_live_lockdown,
            'is_session_suspended': is_session_suspended,
            'session_suspension_reason': getattr(active_session, 'suspension_reason', ''),
            'global_live_url': live_url,
        }
    except Exception:
        return {}


def isolation_context(request):
    """
    Exposes isolation mode status to all templates, allowing Super Admins
    to monitor and control air-gap status globally.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}

    try:
        from config.isolation import get_isolation_status, is_running_on_external_server
        status = get_isolation_status()
        is_ext = is_running_on_external_server()
        return {
            'isolation_status': status,
            'is_system_isolated': status.get('is_isolated', True),
            'is_external_server': is_ext,
        }
    except Exception:
        return {'is_system_isolated': True, 'is_external_server': False}


