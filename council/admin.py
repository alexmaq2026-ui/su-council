from django.contrib import admin
from .models import (
    CouncilSession, Topic, TopicTable, Attendance,
    Decision, Vote, TopicAttachment, TopicRecording,
    LiveSessionDirective
)

@admin.register(CouncilSession)
class CouncilSessionAdmin(admin.ModelAdmin):
    list_display = ('session_number', 'session_cumulative_number', 'academic_year', 'hijri_date', 'date', 'status')
    list_filter = ('status', 'academic_year')
    search_fields = ('title', 'session_number', 'session_cumulative_number')

@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('sub_order', 'title', 'category', 'session', 'status', 'memo_number')
    list_filter = ('category', 'status', 'session')
    search_fields = ('title', 'background', 'memo_number')

@admin.register(TopicTable)
class TopicTableAdmin(admin.ModelAdmin):
    list_display = ('title', 'table_type', 'topic', 'order')
    list_filter = ('table_type',)
    search_fields = ('title', 'topic__title')

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('session', 'member', 'status', 'member_title_snapshot')
    list_filter = ('status', 'session')
    search_fields = ('member__full_name', 'member_title_snapshot')

@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ('topic', 'drafted_by', 'drafted_at')
    search_fields = ('decision_text', 'topic__title')

@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ('topic', 'member', 'choice', 'voted_at')
    list_filter = ('choice',)

@admin.register(TopicAttachment)
class TopicAttachmentAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'topic', 'file_type', 'file_size', 'uploaded_at')

@admin.register(TopicRecording)
class TopicRecordingAdmin(admin.ModelAdmin):
    list_display = ('topic', 'duration_seconds', 'recorded_by', 'recorded_at')

@admin.register(LiveSessionDirective)
class LiveSessionDirectiveAdmin(admin.ModelAdmin):
    list_display = ('session', 'directive_type', 'recipient_name', 'sender', 'is_read', 'created_at')
    list_filter = ('directive_type', 'is_read', 'session')
    search_fields = ('recipient_name', 'message')

