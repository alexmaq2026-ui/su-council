from django.urls import path
from . import views

app_name = 'ai_assistant'

urlpatterns = [
    # /ai/topics/<topic_id>/transcribe/
    path('topics/<int:topic_id>/transcribe/', views.transcribe_view, name='ai-transcribe'),
    # /ai/topics/<topic_id>/analyze/
    path('topics/<int:topic_id>/analyze/', views.analyze_view, name='ai-analyze'),
]
