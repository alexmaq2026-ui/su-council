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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
