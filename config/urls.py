"""
URL Configuration - University Council Management System
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/dashboard/', permanent=False)),

    # Accounts routes (accessible both directly e.g. 'user-create' and as 'accounts:user_create')
    path('', include('accounts.urls')),
    path('', include(('accounts.urls', 'accounts'))),

    # App routes (namespaced by their internal app_name)
    path('', include('council.urls')),
    path('search/', include('search_engine.urls')),
    path('ai/', include('ai_assistant.urls')),
]

import os
from django.shortcuts import redirect
from django.http import Http404, FileResponse
from django.urls import re_path

def media_fallback_view(request, path):
    """
    Resilient media handler:
    1. If file exists on local disk, serve it.
    2. If Supabase Storage is configured, redirect to public Supabase Storage CDN URL.
    """
    clean_path = path.lstrip('/')
    local_path = os.path.join(settings.MEDIA_ROOT, clean_path.replace('/', os.sep))
    if os.path.exists(local_path) and os.path.isfile(local_path):
        return FileResponse(open(local_path, 'rb'))
    
    supabase_url = getattr(settings, 'SUPABASE_URL', '').rstrip('/')
    bucket = getattr(settings, 'SUPABASE_STORAGE_BUCKET', 'council-media')
    if supabase_url:
        return redirect(f"{supabase_url}/storage/v1/object/public/{bucket}/{clean_path}")

    raise Http404('الملف غير موجود.')

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', media_fallback_view, name='media_fallback'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
