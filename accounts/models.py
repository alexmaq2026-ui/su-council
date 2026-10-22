"""
Accounts Models - Custom User & Comprehensive Smart Permission System
University Council Management System
"""
import re
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


def compute_avatar_initials(full_name):
    """Compute clean, meaningful Arabic initials without title prefixes."""
    if not full_name:
        return '؟'
    clean = re.sub(
        r'^(أ\.د\/|ا\.د\/|أ\.د\.|ا\.د\.|أ\.د|ا\.د|د\/|د\.|م\/|م\.|أ\/|أ\.|الأستاذ الدكتور|الاستاذ الدكتور|الأستاذ|الاستاذ|الدكتور|الدكتورة|المهندس|المهندسة)\s*',
        '',
        full_name.strip()
    )
    words = [w for w in re.split(r'\s+', clean) if w and len(w) > 1]
    if len(words) >= 2:
        first = words[0][0]
        last_word = words[-1]
        last = last_word[2] if (last_word.startswith('ال') and len(last_word) > 2) else last_word[0]
        # Avoid double alif parallel lines
        if first in ('ا', 'أ', 'إ') and last in ('ا', 'أ', 'إ'):
            if len(words[0]) > 1:
                first = words[0][1]
        return f'{first}{last}'
    elif words:
        return words[0][:2]
    return full_name[:2]


class UserManager(BaseUserManager):
    """Custom manager for User model."""

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('اسم المستخدم مطلوب')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_super', True)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model for University Council System.
    Zero default permissions - Super Admin or Department Director explicitly assigns them.
    """
    TITLE_CHOICES = [
        ('مدير_النظام', 'مدير النظام الأعلى'),
        ('رئيس_الجامعة', 'رئيس الجامعة'),
        ('نائب_رئيس', 'نائب رئيس الجامعة'),
        ('مستشار', 'مستشار رئيس الجامعة'),
        ('مساعد', 'مساعد رئيس الجامعة'),
        ('امين_عام', 'الأمين العام للجامعة'),
        ('امين_عام_مساعد', 'الأمين العام المساعد'),
        ('عميد', 'عميد كلية'),
        ('نائب_عميد', 'نائب عميد كلية'),
        ('عضو_مجلس', 'عضو مجلس الجامعة'),
        ('رئيس_نقابة', 'رئيس / ممثل نقابة أعضاء هيئة التدريس'),
        ('مدير_عام_المساعدة', 'مدير عام الإدارة العامة المساعدة لشؤون المجلس'),
        ('موظف_المساعدة', 'موظف بالإدارة العامة المساعدة لشؤون المجلس'),
        ('ادارة_مساعدة', 'الإدارة العامة المساعدة - شؤون المجلس'),
        ('اخرى', 'أخرى'),
    ]

    LOGIN_CATEGORY_CHOICES = [
        ('presidency_office', 'مكتب رئيس الجامعة والمستشارون والمساعدون'),
        ('vice_presidents',   'نواب رئيس الجامعة'),
        ('deans',             'عمداء الكليات'),
        ('secretariat_admin', 'الأمانة العامة وإدارة المجلس'),
        ('representatives',   'ممثلو النقابة وأعضاء هيئة التدريس'),
    ]

    username       = models.CharField('اسم المستخدم', max_length=150, unique=True)
    full_name      = models.CharField('الاسم الكامل', max_length=200)
    title          = models.CharField('اللقب / الصفة في المجلس', max_length=40, choices=TITLE_CHOICES, default='اخرى')
    login_category = models.CharField(
        'الموقع في مجلس الجامعة وبوابة الدخول',
        max_length=30,
        choices=LOGIN_CATEGORY_CHOICES,
        default='',
        blank=True,
        help_text='يحدد البوابة التي يظهر ضمنها العضو في شاشة الدخول وموقعه في المجلس'
    )
    official_title = models.CharField('الصفة الرسمية الكاملة بالمجلس', max_length=255, blank=True,
                                      help_text='مثال: عميد كلية الشريعة والقانون أو نائب رئيس الجامعة للشؤون الأكاديمية')
    order          = models.PositiveIntegerField('الترتيب بالمجلس', default=999,
                                                 help_text='ترتيب العضو بحسب كشوفات الحضور بالمحضر')
    department     = models.CharField('الجهة / الكلية / الإدارة', max_length=200, blank=True)
    phone          = models.CharField('رقم الهاتف', max_length=30, blank=True)
    email          = models.EmailField('البريد الإلكتروني', blank=True)
    is_super       = models.BooleanField('مدير النظام الأعلى (سوبر أدمن)', default=False)
    is_active      = models.BooleanField('نشط', default=True)
    is_staff       = models.BooleanField(default=False)
    date_joined    = models.DateTimeField('تاريخ الانضمام', default=timezone.now)
    last_login_ip  = models.GenericIPAddressField('آخر IP', null=True, blank=True)
    avatar_initials = models.CharField('الحروف الأولى', max_length=3, blank=True)

    # On-Demand Personal Direct Link Token
    access_token     = models.CharField('رمز الدخول الشخصي المباشر', max_length=64, blank=True, null=True, unique=True)
    token_created_at = models.DateTimeField('تاريخ توليد رمز الدخول', null=True, blank=True)

    manager = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='subordinates', verbose_name='المسؤول المباشر'
    )

    objects = UserManager()

    USERNAME_FIELD  = 'username'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        verbose_name = 'مستخدم'
        verbose_name_plural = 'المستخدمون'
        ordering = ['order', 'id']

    @property
    def display_title(self):
        return self.official_title or self.get_title_display()

    @classmethod
    def infer_category_from_title(cls, title, is_super=False):
        """Infer one of the 5 login categories from User.title."""
        if is_super or title == 'مدير_النظام':
            return 'secretariat_admin'
        if title in ('رئيس_الجامعة', 'مستشار', 'مساعد'):
            return 'presidency_office'
        if title == 'نائب_رئيس':
            return 'vice_presidents'
        if title in ('عميد', 'نائب_عميد', 'vice_dean_academic'):
            return 'deans'
        if title in ('امين_عام', 'امين_عام_مساعد', 'مدير_عام_المساعدة', 'موظف_المساعدة', 'ادارة_مساعدة'):
            return 'secretariat_admin'
        if title in ('رئيس_نقابة', 'عضو_مجلس'):
            return 'representatives'
        return 'secretariat_admin'

    @staticmethod
    def seat_type_to_category(seat_type):
        """Map EntitySeat.seat_type to one of the 5 login categories."""
        if seat_type in ('presidency', 'advisory'):
            return 'presidency_office'
        if seat_type == 'vice_presidency':
            return 'vice_presidents'
        if seat_type == 'faculty':
            return 'deans'
        if seat_type == 'general_sec':
            return 'secretariat_admin'
        return 'representatives'

    @staticmethod
    def category_to_seat_type(category_key, title=''):
        """Map one of the 5 login categories to the appropriate EntitySeat.seat_type."""
        if category_key == 'presidency_office':
            return 'presidency' if title == 'رئيس_الجامعة' else 'advisory'
        if category_key == 'vice_presidents':
            return 'vice_presidency'
        if category_key == 'deans':
            return 'faculty'
        if category_key == 'secretariat_admin':
            return 'general_sec'
        if category_key == 'representatives':
            return 'syndicate' if title == 'رئيس_نقابة' else 'other'
        return 'other'

    def get_linked_seat_info(self):
        """Return dict with linked active EntitySeat and role for this user, or None."""
        if not self.pk:
            return None
        try:
            from council.models import EntitySeat
            seat = EntitySeat.objects.filter(primary_rep=self, is_active=True).first()
            if seat:
                return {'seat': seat, 'role': 'primary', 'role_label': 'أصيل (الممثل الأول)'}
            seat = EntitySeat.objects.filter(deputy_rep_1=self, is_active=True).first()
            if seat:
                return {'seat': seat, 'role': 'deputy_1', 'role_label': 'نائب أول بالإنابة'}
            seat = EntitySeat.objects.filter(deputy_rep_2=self, is_active=True).first()
            if seat:
                return {'seat': seat, 'role': 'deputy_2', 'role_label': 'نائب ثانٍ بالإنابة'}
        except Exception:
            pass
        return None

    def get_effective_login_category(self):
        """Return the effective login category key for this user."""
        valid_keys = dict(self.LOGIN_CATEGORY_CHOICES)
        if self.login_category and self.login_category in valid_keys:
            return self.login_category
        seat_info = self.get_linked_seat_info()
        if seat_info and seat_info.get('seat'):
            return self.seat_type_to_category(seat_info['seat'].seat_type)
        return self.infer_category_from_title(self.title, is_super=self.is_super)

    def get_effective_login_category_display(self):
        """Return the Arabic display name of the effective login category."""
        cat_map = dict(self.LOGIN_CATEGORY_CHOICES)
        return cat_map.get(self.get_effective_login_category(), 'الأمانة العامة وإدارة المجلس')

    def __str__(self):
        return f'{self.full_name} ({self.display_title})'

    def save(self, *args, **kwargs):
        if self.full_name and not self.avatar_initials:
            self.avatar_initials = compute_avatar_initials(self.full_name)
        if not self.login_category:
            self.login_category = self.infer_category_from_title(self.title, is_super=self.is_super)
        if self.is_super:
            self.is_staff = True
            self.is_superuser = True
        super().save(*args, **kwargs)

    def refresh_from_db(self, *args, **kwargs):
        self._cached_council_perm = None
        super().refresh_from_db(*args, **kwargs)

    def generate_access_token(self):
        """Generate or regenerate on-demand a cryptographically secure random token for direct entry."""
        import secrets
        self.access_token = secrets.token_urlsafe(24)
        self.token_created_at = timezone.now()
        self.save(update_fields=['access_token', 'token_created_at'])
        return self.access_token

    def revoke_access_token(self):
        """Revoke the direct entry token."""
        self.access_token = None
        self.token_created_at = None
        self.save(update_fields=['access_token', 'token_created_at'])

    def get_direct_login_url(self, request=None):
        """Return the absolute or relative direct entry URL for this user."""
        if not self.access_token:
            return ''
        from django.urls import reverse
        rel_path = reverse('accounts:direct_gate_login', kwargs={'token': self.access_token})
        if request:
            return request.build_absolute_uri(rel_path)
        return rel_path

    def get_permission(self):
        """Return the user's Permission object (created with zero permissions if absent)."""
        if not self.pk:
            return None
        if hasattr(self, '_cached_council_perm') and self._cached_council_perm is not None:
            return self._cached_council_perm
        if hasattr(self, '_state') and 'council_permission' in self._state.fields_cache:
            perm = self._state.fields_cache['council_permission']
            if perm is not None:
                self._cached_council_perm = perm
                return perm
        perm, _ = CouncilPermission.objects.get_or_create(user=self)
        self._cached_council_perm = perm
        return perm

    # ── Permission Check Delegation ──────────────────────────────────────────
    def _has_perm(self, attr):
        if self.is_super:
            return True
        perm = self.get_permission()
        return perm is not None and getattr(perm, attr, False)

    # Legacy & High-Level Convenience Properties
    @property
    def can_add(self):
        return self._has_perm('can_add_session') or self._has_perm('can_add_topic') or self._has_perm('can_upload_attachments')
    @property
    def can_edit(self):
        return self._has_perm('can_edit_session') or self._has_perm('can_edit_topic')
    @property
    def can_delete(self):
        return self._has_perm('can_delete_session') or self._has_perm('can_delete_topic') or self._has_perm('can_delete_attachments')
    @property
    def can_vote(self):
        return self._has_perm('can_vote')
    @property
    def can_draft(self):
        return self._has_perm('can_draft_decision')
    @property
    def can_grant(self):
        return self._has_perm('can_grant_permissions')
    @property
    def can_grant_permissions(self):
        return self._has_perm('can_grant_permissions')

    # Granular Operation & Screen Properties (58 total)
    # 1. Sessions & Screens
    @property
    def can_view_sessions(self):       return self._has_perm('can_view_sessions')
    @property
    def can_view_draft_sessions(self): return self._has_perm('can_view_draft_sessions')
    @property
    def can_view_past_sessions(self):  return self._has_perm('can_view_past_sessions')
    @property
    def can_add_session(self):         return self._has_perm('can_add_session')
    @property
    def can_prepare_agenda(self):      return self._has_perm('can_prepare_agenda')
    @property
    def can_edit_session(self):        return self._has_perm('can_edit_session')
    @property
    def can_delete_session(self):      return self._has_perm('can_delete_session')
    @property
    def can_view_attendance(self):     return self._has_perm('can_view_attendance')
    @property
    def can_manage_attendance(self):   return self._has_perm('can_manage_attendance')
    @property
    def can_export_minutes(self):      return self._has_perm('can_export_minutes')
    @property
    def can_verify_integrity(self):    return self._has_perm('can_verify_integrity')

    # 2. Topics
    @property
    def can_view_topics(self):         return self._has_perm('can_view_topics')
    @property
    def can_add_topic(self):           return self._has_perm('can_add_topic')
    @property
    def can_edit_topic(self):          return self._has_perm('can_edit_topic')
    @property
    def can_delete_topic(self):        return self._has_perm('can_delete_topic')
    @property
    def can_change_topic_status(self): return self._has_perm('can_change_topic_status')
    @property
    def can_import_topics(self):       return self._has_perm('can_import_topics')
    @property
    def can_postpone_suspend_topic(self): return self._has_perm('can_postpone_suspend_topic')

    # 3. Tables
    @property
    def can_add_table(self):           return self._has_perm('can_add_table')
    @property
    def can_edit_table(self):          return self._has_perm('can_edit_table')
    @property
    def can_delete_table(self):        return self._has_perm('can_delete_table')

    # 4. Scanner / Attachments
    @property
    def can_view_attachments(self):    return self._has_perm('can_view_attachments')
    @property
    def can_upload_attachments(self):  return self._has_perm('can_upload_attachments')
    @property
    def can_delete_attachments(self):  return self._has_perm('can_delete_attachments')

    # 5. Audio
    @property
    def can_listen_audio(self):        return self._has_perm('can_listen_audio')
    @property
    def can_record_audio(self):        return self._has_perm('can_record_audio')
    @property
    def can_delete_audio(self):        return self._has_perm('can_delete_audio')

    # 6. Voting
    @property
    def can_vote(self):                return self._has_perm('can_vote')
    @property
    def can_view_vote_details(self):   return self._has_perm('can_view_vote_details')

    # 7. Decisions & Correspondence
    @property
    def can_draft_decision(self):          return self._has_perm('can_draft_decision')
    @property
    def can_delete_decision(self):         return self._has_perm('can_delete_decision')
    @property
    def can_upload_signed_decision(self):  return self._has_perm('can_upload_signed_decision')
    @property
    def can_send_decisions(self):          return self._has_perm('can_send_decisions')
    @property
    def can_manage_dispatch_center(self):  return self._has_perm('can_manage_dispatch_center')
    @property
    def can_view_correspondence(self):     return self._has_perm('can_view_correspondence')
    @property
    def can_view_dispatch_log(self):       return self._has_perm('can_view_dispatch_log')
    @property
    def can_export_dispatch_manifest(self): return self._has_perm('can_export_dispatch_manifest')
    @property
    def can_reset_dispatches(self):         return self._has_perm('can_reset_dispatches')

    # 8. Users, Delegation & Account
    @property
    def can_manage_users(self):        return self._has_perm('can_manage_users')
    @property
    def can_delete_user(self):         return self._has_perm('can_delete_user')
    @property
    def can_reset_user_password(self): return self._has_perm('can_reset_user_password')
    @property
    def can_import_members(self):      return self._has_perm('can_import_members')
    @property
    def can_manage_delegates(self):    return self._has_perm('can_manage_delegates')
    @property
    def can_change_password(self):     return self._has_perm('can_change_password')

    # 9. Session Lifecycle & Live Session Management
    @property
    def can_advance_session_stage(self): return self._has_perm('can_advance_session_stage')
    @property
    def can_reopen_frozen_session(self): return self._has_perm('can_reopen_frozen_session')
    @property
    def can_approve_new_session(self):   return self._has_perm('can_approve_new_session')
    @property
    def can_view_stage_logs(self):       return self._has_perm('can_view_stage_logs')
    @property
    def can_view_live_session(self):     return self._has_perm('can_view_live_session')
    @property
    def can_start_session_live(self):    return self._has_perm('can_start_session_live')
    @property
    def can_reopen_topic_live(self):     return self._has_perm('can_reopen_topic_live')
    @property
    def can_suspend_resume_session(self): return self._has_perm('can_suspend_resume_session')
    @property
    def can_set_topic_timer(self):       return self._has_perm('can_set_topic_timer')
    @property
    def can_manage_speak_requests(self): return self._has_perm('can_manage_speak_requests')
    @property
    def can_request_speak(self):         return self._has_perm('can_request_speak')
    @property
    def can_control_recording(self):     return self._has_perm('can_control_recording')
    @property
    def can_request_exit_permit(self):   return self._has_perm('can_request_exit_permit')
    @property
    def can_approve_exit_permit(self):   return self._has_perm('can_approve_exit_permit')
    @property
    def can_view_projector(self):        return self._has_perm('can_view_projector')
    @property
    def can_view_analytics(self):        return self._has_perm('can_view_analytics')
    @property
    def can_open_previous_minutes(self): return self._has_perm('can_open_previous_minutes')
    @property
    def can_broadcast_previous_minutes(self): return self._has_perm('can_broadcast_previous_minutes')
    @property
    def can_moderate_live_session(self): return self._has_perm('can_moderate_live_session')
    @property
    def enforce_force_majeure(self):
        """Returns True only if the Super Admin explicitly applied Force Majeure on this user."""
        if self.is_super:
            return False
        perm = self.get_permission()
        return bool(perm and getattr(perm, 'enforce_force_majeure', False))

    # 10. Search, Notifications, Smart Reader & Audit
    @property
    def can_search_minutes(self):        return self._has_perm('can_search_minutes')
    @property
    def can_search_person(self):         return self._has_perm('can_search_person')
    @property
    def can_view_notifications(self):    return self._has_perm('can_view_notifications')
    @property
    def can_view_notification_log(self): return self._has_perm('can_view_notification_log')
    @property
    def can_manage_sms_template(self):   return self._has_perm('can_manage_sms_template')
    @property
    def can_use_smart_reader(self):      return self._has_perm('can_use_smart_reader')
    @property
    def can_manage_smart_reader(self):   return self._has_perm('can_manage_smart_reader')
    @property
    def can_view_audit_log(self):        return self._has_perm('can_view_audit_log')
    @property
    def can_toggle_audit_backup(self):   return self._has_perm('can_toggle_audit_backup')
    @property
    def can_clear_audit_log(self):       return self._has_perm('can_clear_audit_log')
    @property
    def can_toggle_sms(self):                  return self._has_perm('can_toggle_sms')
    @property
    def can_toggle_inapp(self):                return self._has_perm('can_toggle_inapp')
    @property
    def can_clear_notification_log(self):      return self._has_perm('can_clear_notification_log')
    @property
    def can_manual_backup_notifications(self): return self._has_perm('can_manual_backup_notifications')

    @property
    def has_any_permission(self):
        if self.is_super:
            return True
        perm = self.get_permission()
        return perm is not None and perm.count_granted() > 0

    @property
    def granted_permissions_count(self):
        if self.is_super:
            return len(CouncilPermission.ALL_PERMISSION_FIELDS)
        perm = self.get_permission()
        return perm.count_granted() if perm else 0

    @property
    def is_voting_member_core(self):
        if self.is_super:
            return False
        perm = self.get_permission()
        return perm.is_voting_member_core() if perm else False


class CouncilPermission(models.Model):
    """
    Granular Smart Permission Matrix.
    Contains 58 discrete screen and button/operation permissions.
    Zero default permissions - all controlled explicitly by Admin.
    """
    ALL_PERMISSION_FIELDS = [
        # 1. Sessions
        'can_view_sessions', 'can_view_draft_sessions', 'can_view_past_sessions',
        'can_add_session', 'can_prepare_agenda', 'can_edit_session', 'can_delete_session',
        'can_view_attendance', 'can_manage_attendance',
        'can_export_minutes', 'can_verify_integrity',
        # 2. Topics
        'can_view_topics', 'can_add_topic', 'can_edit_topic',
        'can_delete_topic', 'can_change_topic_status', 'can_import_topics',
        'can_postpone_suspend_topic',
        # 3. Tables
        'can_add_table', 'can_edit_table', 'can_delete_table',
        # 4. Attachments
        'can_view_attachments', 'can_upload_attachments', 'can_delete_attachments',
        # 5. Audio
        'can_listen_audio', 'can_record_audio', 'can_delete_audio',
        # 6. Voting
        'can_vote', 'can_view_vote_details',
        # 7. Decisions & Correspondence
        'can_draft_decision', 'can_delete_decision',
        'can_upload_signed_decision', 'can_send_decisions', 'can_manage_dispatch_center',
        'can_view_correspondence', 'can_view_dispatch_log',
        'can_export_dispatch_manifest', 'can_reset_dispatches',
        # 8. Users & Delegation
        'can_manage_users', 'can_delete_user', 'can_reset_user_password',
        'can_import_members', 'can_grant_permissions',
        'can_manage_delegates', 'can_change_password',
        # 9. Lifecycle & Live Session
        'can_advance_session_stage', 'can_reopen_frozen_session', 'can_approve_new_session',
        'can_view_stage_logs',
        'can_view_live_session', 'can_start_session_live', 'can_reopen_topic_live', 'can_suspend_resume_session',
        'can_set_topic_timer',
        'can_manage_speak_requests', 'can_request_speak', 'can_control_recording',
        'can_request_exit_permit', 'can_approve_exit_permit',
        'can_view_projector', 'can_view_analytics',
        'can_open_previous_minutes', 'can_broadcast_previous_minutes',
        'can_moderate_live_session', 'enforce_force_majeure',
        # 10. Search, Notifications, Smart Reader & Audit
        'can_search_minutes', 'can_search_person',
        'can_view_notifications', 'can_view_notification_log',
        'can_toggle_sms', 'can_toggle_inapp',
        'can_clear_notification_log', 'can_manual_backup_notifications',
        'can_manage_sms_template', 'can_use_smart_reader',
        'can_manage_smart_reader', 'can_view_audit_log',
        'can_toggle_audit_backup', 'can_clear_audit_log',
    ]

    # 🌟 الصلاحيات الأساسية للأعضاء من لهم حق التصويت (11 صلاحية قياسية معتمدة)
    VOTING_MEMBER_CORE_PERMISSIONS = [
        'can_view_sessions',        # عرض شاشة قائمة الجلسات وتفاصيل الجلسة
        'can_view_topics',          # عرض تفاصيل الموضوعات والحيثيات والقرارات
        'can_view_attachments',     # معاينة وتحميل أوليات ومرفقات الموضوع
        'can_vote',                 # ممارسة حق التصويت (موافق/مرفوض/متحفظ)
        'can_view_correspondence',  # عرض شاشة مراسلات الكلية وتحميل القرارات الواردة
        'can_manage_delegates',     # إدارة الممثلين والتفويض بالإنابة
        'can_change_password',      # تغيير كلمة المرور الخاصة بالحساب
        'can_view_live_session',    # دخول غرفة الجلسة الحية (Live)
        'can_request_speak',        # طلب المداخلة في الجلسة
        'can_request_exit_permit',  # طلب الإذن بالخروج النهائي من الجلسة
        'can_view_notifications',   # عرض جرس ومركز التنبيهات والإشعارات
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name='council_permission',
        verbose_name='المستخدم'
    )

    # 1. Sessions Screens & Operations
    can_view_sessions       = models.BooleanField('عرض شاشة قائمة الجلسات وتفاصيل الجلسة', default=False)
    can_view_draft_sessions = models.BooleanField('عرض الجلسات في مرحلة التحضير (المسودة)', default=False)
    can_view_past_sessions  = models.BooleanField('الاطلاع على الجلسات السابقة', default=False,
                                                  help_text='استعراض أرشيف ومحاضر وتفاصيل ومواضيع الجلسات السابقة للمجلس التي تسبق الجلسة الأخيرة')
    can_add_session         = models.BooleanField('إنشاء جلسة جديدة', default=False)
    can_prepare_agenda      = models.BooleanField('إعداد جدول الأعمال (الشاشة المخصصة)', default=False)
    can_edit_session        = models.BooleanField('تعديل بيانات الجلسة', default=False)
    can_delete_session      = models.BooleanField('حذف الجلسة', default=False)
    can_view_attendance     = models.BooleanField('عرض كشف الحضور والغياب في الجلسة', default=False)
    can_manage_attendance   = models.BooleanField('إدارة ورصد كشف الحضور', default=False)
    can_export_minutes      = models.BooleanField('تصدير المحضر إلى Word', default=False)
    can_verify_integrity    = models.BooleanField('فحص مطابقة البصمة التشفيرية وتحميل PDF المؤرشف', default=False)

    # 2. Topics Screens & Operations
    can_view_topics            = models.BooleanField('عرض تفاصيل الموضوعات والحيثيات والقرارات', default=False)
    can_add_topic              = models.BooleanField('إضافة موضوع جديد', default=False)
    can_edit_topic             = models.BooleanField('تعديل موضوع قائم', default=False)
    can_delete_topic           = models.BooleanField('حذف موضوع', default=False)
    can_change_topic_status    = models.BooleanField('تغيير حالة الموضوع', default=False)
    can_import_topics          = models.BooleanField('استيراد مواضيع من Word', default=False)
    can_postpone_suspend_topic = models.BooleanField('تعليق وتأجيل موضوعات جدول الأعمال أثناء الانعقاد', default=False)

    # 3. Tables Operations
    can_add_table           = models.BooleanField('إضافة وبناء جداول البيانات', default=False)
    can_edit_table          = models.BooleanField('تعديل الجداول والصفوف والحسابات', default=False)
    can_delete_table        = models.BooleanField('حذف جداول البيانات', default=False)

    # 4. Scanner / Attachments Operations
    can_view_attachments    = models.BooleanField('معاينة وتحميل أوليات ومرفقات الموضوع', default=False)
    can_upload_attachments  = models.BooleanField('رفع أوليات ومرفقات الإسكانر', default=False)
    can_delete_attachments  = models.BooleanField('حذف المستندات المرفقة', default=False)

    # 5. Audio & Discussions Operations
    can_listen_audio        = models.BooleanField('الاستماع وتحميل التسجيلات الصوتية', default=False)
    can_record_audio        = models.BooleanField('تسجيل نقاش القاعة صوتياً', default=False)
    can_delete_audio        = models.BooleanField('حذف التسجيلات الصوتية', default=False)

    # 6. Voting Operations
    can_vote                = models.BooleanField('ممارسة حق التصويت (موافق/مرفوض/متحفظ)', default=False)
    can_view_vote_details   = models.BooleanField('مشاهدة تفاصيل وملاحظات تصويت الأعضاء', default=False)

    # 7. Decisions & Correspondence Operations
    can_draft_decision          = models.BooleanField('صياغة واعتماد القرارات الرسمية', default=False)
    can_delete_decision         = models.BooleanField('حذف أو تعديل القرارات المعتمدة', default=False)
    can_upload_signed_decision  = models.BooleanField('رفع مستند القرار الموقّع رسمياً', default=False)
    can_send_decisions          = models.BooleanField('إرسال القرارات الموقَّعة إلى الجهات', default=False)
    can_manage_dispatch_center  = models.BooleanField('إدارة مركز تعميم القرارات والمراسلات الرسمية', default=False,
                                                     help_text='الوصول للمركز الرئيسي لتعميم المحاضر والقرارات والوثائق الملحقة الحرة على الكليات')
    can_view_correspondence     = models.BooleanField('عرض شاشة مراسلات الكلية وتحميل القرارات الواردة', default=False)
    can_view_dispatch_log       = models.BooleanField('عرض ومتابعة سجل إرسال واستلام القرارات', default=False)
    can_export_dispatch_manifest = models.BooleanField(
        'تصدير كشف وفهرس المراسلات (Excel)', default=False,
        help_text='تصدير كشف شامل بعناوين وتواريخ وبيانات استلام كافة المراسلات لجميع الكليات بصيغة Excel'
    )
    can_reset_dispatches         = models.BooleanField(
        'تصفير وتطهير سجلات مراسلات الكليات', default=False,
        help_text='صلاحية حساسة لتصفير وإفراغ جميع المراسلات وصناديق الوارد لدى كافة الكليات والأعضاء'
    )

    # 8. Users, Delegation & Account Operations
    can_manage_users          = models.BooleanField('إضافة وتعديل بيانات المستخدمين', default=False)
    can_delete_user           = models.BooleanField('حذف وتعطيل حسابات المستخدمين', default=False)
    can_reset_user_password   = models.BooleanField('إعادة تعيين كلمات المرور للمستخدمين', default=False)
    can_import_members        = models.BooleanField('استيراد أعضاء المجلس (Excel/Word)', default=False)
    can_grant_permissions     = models.BooleanField('تخويل وإدارة صلاحيات المستخدمين', default=False)
    can_manage_delegates      = models.BooleanField('إدارة الممثلين والتفويض بالإنابة', default=False)
    can_change_password       = models.BooleanField('تغيير كلمة المرور الخاصة بالحساب', default=False)

    # 9. Session Lifecycle & Live Session Management
    can_advance_session_stage  = models.BooleanField('نقل الجلسة بين المراحل الخمس', default=False)
    can_reopen_frozen_session  = models.BooleanField('إعادة فتح الجلسة المجمّدة (+ تأكيد كلمة المرور)', default=False)
    can_approve_new_session    = models.BooleanField('الموافقة على جلسة جديدة قبل إغلاق السابقة', default=False)
    can_view_stage_logs        = models.BooleanField('عرض سجل مراحل الجلسة في الشريط الجانبي', default=False,
                                                     help_text='إظهار بطاقة سجل مراحل الجلسة وتتبع الانتقالات والمسؤول عنها في شاشة تفاصيل الجلسة')
    can_view_live_session      = models.BooleanField('دخول غرفة الجلسة الحية (Live)', default=False)
    can_start_session_live     = models.BooleanField('إدارة الجلسة الحية وفتح التصويت وإنهاؤه', default=False)
    can_reopen_topic_live      = models.BooleanField('إعادة فتح المواضيع للنقاش والتصويت أثناء الانعقاد', default=False,
                                                     help_text='صلاحية إعادة طرح أي موضوع مغلق أو محسوب النتائج للنقاش أو إعادة فتح باب التصويت عليه')
    can_suspend_resume_session = models.BooleanField('تعليق واستئناف ورفع الجلسة الحية (وتحرير القاعة)', default=False)
    can_set_topic_timer        = models.BooleanField('ضبط وقت المواضيع وتمديده', default=False)
    can_manage_speak_requests  = models.BooleanField('إدارة طلبات المداخلة (سماح / رفض / إنهاء)', default=False)
    can_request_speak          = models.BooleanField('طلب المداخلة في الجلسة', default=False)
    can_control_recording      = models.BooleanField('التحكم في التسجيل الصوتي للجلسة (بدء / إيقاف / إنهاء)', default=False)
    can_request_exit_permit    = models.BooleanField('طلب الإذن بالخروج النهائي من الجلسة', default=False)
    can_approve_exit_permit    = models.BooleanField('البتّ في طلبات الإذن بالخروج', default=False)
    can_view_projector         = models.BooleanField('عرض شاشة القاعة البروجكتر (Projector)', default=False)
    can_view_analytics         = models.BooleanField('عرض شاشة التقرير التحليلي للجلسة', default=False)
    can_open_previous_minutes  = models.BooleanField('زر المحضر السابق في جدول الأعمال', default=False,
                                                    help_text='إظهار زر «المحضر السابق» في جدول مواضيع الجلسة لفتح نافذة مطالعته ومصادقته')
    can_broadcast_previous_minutes = models.BooleanField('زر بث لشاشات الأعضاء في شاشة المحضر السابق', default=False,
                                                         help_text='إظهار وإتاحة زر «بث لشاشات الأعضاء» لبث المحضر السابق لشاشات الأعضاء وإيقافه')
    can_moderate_live_session      = models.BooleanField('اللوحة العائمة للتوجيه والتنبيه التفاعلي ونقاط النظام للأعضاء', default=False,
                                                         help_text='إظهار اللوحة العائمة المنكمشة لرئيس الجلسة أو المفوّض لإرسال نقاط النظام ورسائل الهدوء والتوجيهات المخصصة للأعضاء الحاضرين')
    enforce_force_majeure          = models.BooleanField('زر تطبيق القوة القاهرة (تجميد شاشة العضو والتنقل أثناء النقاش)', default=False,
                                                         help_text='تطبيق القوة القاهرة حصراً على هذا العضو بقرار المدير الأعلى؛ بحيث تُوجَّه شاشته إجبارياً لموضوع النقاش وتُجمَّد روابط التنقل في السايدبار والنافبار أثناء انعقاد الجلسة')

    # 10. Search, Notifications, Smart Reader & Audit
    can_search_minutes        = models.BooleanField('استخدام شاشة البحث في المحاضر', default=False)
    can_search_person         = models.BooleanField('استخدام شاشة البحث عن شخص', default=False)
    can_view_notifications    = models.BooleanField('عرض جرس ومركز التنبيهات والإشعارات', default=False)
    can_view_notification_log = models.BooleanField('عرض سجل تسليم التنبيهات ورسائل SMS', default=False)
    can_manage_sms_template   = models.BooleanField('إعداد قالب الرسائل النصية (SMS)', default=False)
    can_use_smart_reader      = models.BooleanField('استخدام القراءة الذكية للمحاضر والمواضيع', default=False)
    can_manage_smart_reader   = models.BooleanField('إدارة إعدادات وسجل القراءة الذكية', default=False)
    can_view_audit_log        = models.BooleanField('عرض سجل رقابة المستخدمين', default=False)
    can_toggle_audit_backup   = models.BooleanField('إيقاف/تشغيل نظام رقابة المستخدمين والنسخ الاحتياطي', default=False)
    can_clear_audit_log       = models.BooleanField('تصفير ومسح سجلات الرقابة والنسخ الاحتياطي', default=False)
    can_toggle_sms                  = models.BooleanField('إيقاف/تشغيل رسائل SMS', default=False)
    can_toggle_inapp                = models.BooleanField('إيقاف/تشغيل إشعارات النظام المباشرة للأعضاء', default=False)
    can_clear_notification_log      = models.BooleanField('تصفير ومسح سجلات التنبيهات', default=False)
    can_manual_backup_notifications = models.BooleanField('أخذ نسخة احتياطية يدوية لسجلات التنبيهات', default=False)

    # Audit & Delegation Info
    granted_by  = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='granted_permissions', verbose_name='مُخوَّل من'
    )
    granted_at  = models.DateTimeField('تاريخ التخويل', auto_now=True)
    notes       = models.TextField('ملاحظات التخويل', blank=True)

    class Meta:
        verbose_name = 'صلاحيات المستخدم'
        verbose_name_plural = 'مصفوفة الصلاحيات'

    def __str__(self):
        return f'صلاحيات {self.user.full_name}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if hasattr(self, '_state') and 'user' in self._state.fields_cache:
            u = self._state.fields_cache['user']
            if u is not None:
                u._cached_council_perm = self

    def count_granted(self):
        """Return total number of granted permissions (out of 60)."""
        return sum(1 for f in self.ALL_PERMISSION_FIELDS if getattr(self, f, False))

    def get_permissions_list(self):
        """Return user-friendly list of granted permission labels."""
        labels = []
        for f in self.ALL_PERMISSION_FIELDS:
            if getattr(self, f, False):
                try:
                    field_obj = self._meta.get_field(f)
                    labels.append(str(field_obj.verbose_name))
                except Exception:
                    labels.append(f)
        return labels

    def apply_voting_member_core_permissions(self, granted_by_user=None, notes='منح الصلاحيات الأساسية للأعضاء من لهم حق التصويت'):
        """Grant the 11 core voting member permissions and clear all other permissions."""
        for f in self.ALL_PERMISSION_FIELDS:
            setattr(self, f, f in self.VOTING_MEMBER_CORE_PERMISSIONS)
        if granted_by_user:
            self.granted_by = granted_by_user
        if notes:
            self.notes = notes
        self.save()
        return self

    def is_voting_member_core(self):
        """Check if granted permissions match the voting member core set."""
        granted_set = {f for f in self.ALL_PERMISSION_FIELDS if getattr(self, f, False)}
        return granted_set == set(self.VOTING_MEMBER_CORE_PERMISSIONS)
