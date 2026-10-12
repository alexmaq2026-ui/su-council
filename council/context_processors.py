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
        active_session = CouncilSession.objects.filter(status='active').first()
        if not active_session:
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
        is_on_live_page = request.path.startswith(live_url)
        is_controller = bool(user.is_super or user.can_start_session_live)
        has_voting_right = bool(getattr(user, 'can_vote', False))
        # يقتصر القفل الصارم على الأعضاء أصحاب حق التصويت فقط؛ أما الكادر الإداري والمساعد فيتاح له التنقل بحرية
        # وفي حالة تعليق الجلسة (الاستراحة)، يتم تحرير شاشات جميع الأعضاء فوراً
        is_session_suspended = bool(getattr(active_session, 'is_suspended', False))
        is_member_live_lockdown = bool(is_on_live_page and not is_controller and has_voting_right and not is_session_suspended)

        return {
            'global_live_session': active_session,
            'global_active_topic': active_topic,
            'is_on_live_page': is_on_live_page,
            'is_live_controller': is_controller,
            'is_member_live_lockdown': is_member_live_lockdown,
            'is_session_suspended': is_session_suspended,
            'session_suspension_reason': getattr(active_session, 'suspension_reason', ''),
            'global_live_url': live_url,
        }
    except Exception:
        return {}
