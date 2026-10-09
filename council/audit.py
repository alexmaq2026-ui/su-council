"""
Audit Utilities - University Council Management System
Provides log_action() for recording system events into AuditLog.
Audit logging must never break the main request flow.
"""


def get_client_ip(request):
    """Extract the real client IP from request headers."""
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip() or None
    return request.META.get('REMOTE_ADDR') or None


def log_action(user, action, obj=None, field_changes=None,
               request=None, notes='', object_repr=''):
    """
    Record an audit event.

    Args:
        user:          User instance (or None / AnonymousUser)
        action:        one of AuditLog.ACTION_CHOICES keys
        obj:           any Django model instance (optional)
        field_changes: dict {field: {'old': ..., 'new': ...}} (optional)
        request:       HttpRequest used to extract the IP (optional)
        notes:         free-text note
        object_repr:   override automatic object description
    """
    try:
        from .models import AuditLog
        real_user = user if (user is not None and getattr(user, 'is_authenticated', False)) else None
        AuditLog.objects.create(
            user=real_user,
            action=action,
            model_name=obj.__class__.__name__ if obj is not None else '',
            object_id=str(obj.pk) if (obj is not None and getattr(obj, 'pk', None) is not None) else '',
            object_repr=(object_repr or (str(obj) if obj is not None else ''))[:300],
            field_changes=field_changes or {},
            ip_address=get_client_ip(request),
            notes=(notes or '')[:2000],
        )
    except Exception:
        # Never let audit logging crash the application
        pass
