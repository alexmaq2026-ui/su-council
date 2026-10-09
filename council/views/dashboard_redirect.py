"""
Session views + Dashboard redirect
University Council Management System
"""
from django.shortcuts import redirect


def dashboard_redirect(request):
    """Redirect /dashboard/ to accounts dashboard."""
    from accounts.views import dashboard_view
    return dashboard_view(request)
