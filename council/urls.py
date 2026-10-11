"""
Council App URLs - University Council Management System
Namespaced under 'council'.
Supports both underscore and hyphenated names for flexibility.
"""
from django.urls import path
from council.views import (
    session_views, topic_views, vote_views, decision_views,
    export_views, table_views, live_session_views, dispatch_views,
    notification_views, smart_reader_views
)

app_name = 'council'

urlpatterns = [
    # ── Sessions ─────────────────────────────────────────────────────────
    path('sessions/', session_views.session_list_view, name='session_list'),
    path('sessions/', session_views.session_list_view, name='session-list'),
    path('sessions/new/', session_views.session_create_view, name='session_create'),
    path('sessions/new/', session_views.session_create_view, name='session-create'),
    path('sessions/<int:pk>/', session_views.session_detail_view, name='session_detail'),
    path('sessions/<int:pk>/', session_views.session_detail_view, name='session-detail'),
    path('sessions/<int:pk>/edit/', session_views.session_edit_view, name='session_edit'),
    path('sessions/<int:pk>/edit/', session_views.session_edit_view, name='session-edit'),
    path('sessions/<int:pk>/delete/', session_views.session_delete_view, name='session_delete'),
    path('sessions/<int:pk>/delete/', session_views.session_delete_view, name='session-delete'),
    path('sessions/<int:pk>/attendance/', session_views.session_attendance_view, name='session_attendance'),
    path('sessions/<int:pk>/attendance/', session_views.session_attendance_view, name='session-attendance'),
    path('sessions/<int:pk>/export/', export_views.export_session_word_view, name='session_export'),
    path('sessions/<int:pk>/export/', export_views.export_session_word_view, name='session-export'),

    # ── Lifecycle, Requests & Audit (Phase 1) ────────────────────────────
    path('sessions/<int:pk>/advance/', session_views.session_advance_stage_view, name='session_advance_stage'),
    path('sessions/<int:pk>/advance/', session_views.session_advance_stage_view, name='session-advance-stage'),
    path('sessions/<int:pk>/reopen/', session_views.session_reopen_view, name='session_reopen'),
    path('sessions/<int:pk>/reopen/', session_views.session_reopen_view, name='session-reopen'),
    path('requests/<int:pk>/review/', session_views.new_session_request_review_view, name='new_session_request_review'),
    path('audit-log/', session_views.audit_log_view, name='audit_log'),
    path('audit-log/', session_views.audit_log_view, name='audit-log'),
    path('backups/now/', session_views.backup_now_view, name='backup_now'),

    # ── Topics ────────────────────────────────────────────────────────────
    path('sessions/<int:session_pk>/topics/new/', topic_views.topic_create_view, name='topic_create'),
    path('sessions/<int:session_pk>/topics/new/', topic_views.topic_create_view, name='topic-create'),
    path('sessions/<int:session_pk>/topics/import/', topic_views.import_word_view, name='topic_import'),
    path('sessions/<int:session_pk>/topics/import/', topic_views.import_word_view, name='topic-import'),
    path('sessions/<int:session_pk>/topics/import/', topic_views.import_word_view, name='import_word'),
    path('topics/<int:pk>/', topic_views.topic_detail_view, name='topic_detail'),
    path('topics/<int:pk>/', topic_views.topic_detail_view, name='topic-detail'),
    path('topics/<int:pk>/edit/', topic_views.topic_edit_view, name='topic_edit'),
    path('topics/<int:pk>/edit/', topic_views.topic_edit_view, name='topic-edit'),
    path('topics/<int:pk>/delete/', topic_views.topic_delete_view, name='topic_delete'),
    path('topics/<int:pk>/delete/', topic_views.topic_delete_view, name='topic-delete'),
    path('topics/<int:pk>/status/', topic_views.topic_status_view, name='topic_status'),
    path('topics/<int:pk>/status/', topic_views.topic_status_view, name='topic-status'),

    # ── Topic Tables (Dynamic & Auto-Sum) ─────────────────────────────────
    path('topics/<int:topic_pk>/tables/new/', table_views.table_create_view, name='table_create'),
    path('topics/<int:topic_pk>/tables/new/', table_views.table_create_view, name='table-create'),
    path('tables/<int:pk>/edit/', table_views.table_edit_view, name='table_edit'),
    path('tables/<int:pk>/edit/', table_views.table_edit_view, name='table-edit'),
    path('tables/<int:pk>/delete/', table_views.table_delete_view, name='table_delete'),
    path('tables/<int:pk>/delete/', table_views.table_delete_view, name='table-delete'),

    # ── Attachments ───────────────────────────────────────────────────────
    path('topics/<int:topic_pk>/attach/', topic_views.attachment_upload_view, name='attachment_upload'),
    path('topics/<int:topic_pk>/attach/', topic_views.attachment_upload_view, name='attachment-upload'),
    path('attachments/<int:pk>/delete/', topic_views.attachment_delete_view, name='attachment_delete'),
    path('attachments/<int:pk>/delete/', topic_views.attachment_delete_view, name='attachment-delete'),

    # ── Recordings ────────────────────────────────────────────────────────
    path('topics/<int:topic_pk>/record/save/', topic_views.recording_save_view, name='recording_save'),
    path('topics/<int:topic_pk>/record/save/', topic_views.recording_save_view, name='recording-save'),
    path('recordings/<int:pk>/delete/', topic_views.recording_delete_view, name='recording_delete'),
    path('recordings/<int:pk>/delete/', topic_views.recording_delete_view, name='recording-delete'),

    # ── Votes ─────────────────────────────────────────────────────────────
    path('topics/<int:topic_pk>/vote/', vote_views.vote_view, name='vote'),
    path('topics/<int:topic_pk>/vote/', vote_views.vote_view, name='topic_vote'),
    path('topics/<int:topic_pk>/vote/results/', vote_views.vote_results_view, name='vote_results'),
    path('topics/<int:topic_pk>/vote/results/', vote_views.vote_results_view, name='vote-results'),

    # ── Decisions ─────────────────────────────────────────────────────────
    path('topics/<int:topic_pk>/decision/', decision_views.decision_create_edit_view, name='decision_edit'),
    path('topics/<int:topic_pk>/decision/', decision_views.decision_create_edit_view, name='decision-edit'),
    path('topics/<int:topic_pk>/decision/delete/', decision_views.decision_delete_view, name='decision_delete'),
    path('topics/<int:topic_pk>/decision/delete/', decision_views.decision_delete_view, name='decision-delete'),

    # ── Phase 3: Live Session, Projector & Analytics ─────────────────────
    path('sessions/<int:session_pk>/live/', live_session_views.session_live_view, name='session_live'),
    path('sessions/<int:session_pk>/live/', live_session_views.session_live_view, name='session-live'),
    path('sessions/<int:session_pk>/projector/', live_session_views.session_projector_view, name='session_projector'),
    path('sessions/<int:session_pk>/projector/', live_session_views.session_projector_view, name='session-projector'),
    path('sessions/<int:session_pk>/analytics/', live_session_views.session_analytics_view, name='session_analytics'),
    path('sessions/<int:session_pk>/analytics/', live_session_views.session_analytics_view, name='session-analytics'),

    # APIs for Live Session & Topic State Control
    path('api/topics/<int:topic_pk>/control/', live_session_views.api_topic_control, name='api_topic_control'),
    path('api/topics/<int:topic_pk>/state/', live_session_views.api_topic_state, name='api_topic_state'),
    path('api/topics/<int:topic_pk>/quick-view/', live_session_views.api_topic_quick_view, name='api_topic_quick_view'),
    path('api/sessions/<int:session_pk>/quorum/', live_session_views.api_session_quorum, name='api_session_quorum'),
    path('api/sessions/<int:session_pk>/active-topic/', live_session_views.api_session_active_topic, name='api_session_active_topic'),

    # APIs for Speech Queue (SpeakRequest)
    path('api/sessions/<int:session_pk>/speak/toggle/', live_session_views.api_speak_request_toggle, name='api_speak_request_toggle'),
    path('api/speak-requests/<int:request_pk>/action/', live_session_views.api_speak_request_action, name='api_speak_request_action'),
    path('api/sessions/<int:session_pk>/speak/queue/', live_session_views.api_speak_queue, name='api_speak_queue'),

    # APIs for Continuous Session Recording
    path('api/sessions/<int:session_pk>/recording/action/', live_session_views.api_session_recording_action, name='api_session_recording_action'),
    path('api/sessions/<int:session_pk>/recording/chunk/', live_session_views.api_session_recording_chunk, name='api_session_recording_chunk'),

    # APIs for Exit Permits
    path('api/sessions/<int:session_pk>/exit-permit/request/', live_session_views.api_exit_permit_request, name='api_exit_permit_request'),
    path('api/exit-permits/<int:permit_pk>/action/', live_session_views.api_exit_permit_action, name='api_exit_permit_action'),

    # ── Phase 4: Signed Decisions, Faculty Dispatches & Digital Hash ─────
    path('topics/<int:topic_pk>/signed-decision/upload/', dispatch_views.upload_signed_decision_view, name='upload_signed_decision'),
    path('topics/<int:topic_pk>/signed-decision/dispatch/', dispatch_views.dispatch_signed_decision_view, name='dispatch_signed_decision'),
    path('correspondence/', dispatch_views.entity_correspondence_view, name='entity_correspondence'),
    path('correspondence/<int:seat_pk>/', dispatch_views.entity_correspondence_view, name='entity_correspondence'),
    path('correspondence/<int:seat_pk>/', dispatch_views.entity_correspondence_view, name='entity_correspondence_seat'),
    path('dispatches/<int:dispatch_pk>/file/', dispatch_views.view_signed_decision_file_view, name='view_signed_decision_file'),
    path('dispatches/log/', dispatch_views.dispatch_log_view, name='dispatch_log'),
    path('api/sessions/<int:session_pk>/verify-hash/', dispatch_views.verify_session_hash_view, name='verify_session_hash'),
    path('sessions/<int:session_pk>/archived-pdf/', dispatch_views.export_archived_pdf_view, name='session_archived_pdf'),

    # ── Phase 5: Notifications & SMS Messaging Engine ────────────────────
    path('api/notifications/unread/', notification_views.api_unread_notifications, name='api_unread_notifications'),
    path('api/notifications/<int:notif_pk>/read/', notification_views.api_mark_notification_read, name='api_mark_notification_read'),
    path('api/notifications/read-all/', notification_views.api_mark_all_notifications_read, name='api_mark_all_notifications_read'),
    path('notifications/', notification_views.notification_list_view, name='notification_list'),
    path('notifications/log/', notification_views.notification_log_view, name='notification_log'),
    path('notifications/sms-templates/', notification_views.sms_template_list_view, name='sms_template_list'),
    path('notifications/sms-templates/<int:pk>/edit/', notification_views.sms_template_edit_view, name='sms_template_edit'),

    # ── Phase 6: Smart Audio Reader & Neural Cloud TTS (المقترح م7) ──────
    path('api/smart-reader/data/', smart_reader_views.api_smart_reader_data, name='api_smart_reader_data'),
    path('api/smart-reader/synthesize/', smart_reader_views.api_smart_reader_synthesize, name='api_smart_reader_synthesize'),
    path('api/smart-reader/log/', smart_reader_views.api_smart_reader_log, name='api_smart_reader_log'),
    # Backward-compatible aliases for legacy /council/ prefix
    path('council/api/smart-reader/data/', smart_reader_views.api_smart_reader_data),
    path('council/api/smart-reader/synthesize/', smart_reader_views.api_smart_reader_synthesize),
    path('council/api/smart-reader/log/', smart_reader_views.api_smart_reader_log),
    path('smart-reader/settings/', smart_reader_views.smart_reader_settings_view, name='smart_reader_settings'),
]
