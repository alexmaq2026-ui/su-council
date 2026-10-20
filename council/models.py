"""
Council Models - Sessions, Topics, Votes, Decisions, Lifecycle & Audit
University Council Management System
"""
from django.db import models
from django.conf import settings
from django.utils import timezone


# ── Constants ──────────────────────────────────────────────────────────────────
TOPIC_CATEGORIES = [
    ('general',      'المواضيع العامة'),
    ('appointments', 'مواضيع التعيينات'),
    ('academic',     'مواضيع الشؤون الأكاديمية وشؤون أعضاء هيئة التدريس'),
    ('postgrad',     'مواضيع الدراسات العليا والبحث العلمي'),
    ('students',     'مواضيع شؤون الطلاب'),
    ('centers',      'مواضيع شؤون المراكز'),
    ('new_business', 'ما استجد من أعمال'),
]

# ── Visual Identity / Themes for Council Topics & Categories ───────────────────
CATEGORY_THEMES = {
    'general': {
        'color': '#1e3a8a',          # Royal Navy
        'bg_soft': '#eff6ff',
        'border_color': '#93c5fd',
        'icon': 'bi-building',
        'badge_bg': '#dbeafe',
        'badge_text': '#1e40af',
    },
    'appointments': {
        'color': '#059669',          # Emerald Green
        'bg_soft': '#ecfdf5',
        'border_color': '#6ee7b7',
        'icon': 'bi-person-plus-fill',
        'badge_bg': '#d1fae5',
        'badge_text': '#065f46',
    },
    'academic': {
        'color': '#4338ca',          # Deep Indigo
        'bg_soft': '#eef2ff',
        'border_color': '#a5b4fc',
        'icon': 'bi-mortarboard-fill',
        'badge_bg': '#e0e7ff',
        'badge_text': '#3730a3',
    },
    'postgrad': {
        'color': '#7c3aed',          # Royal Purple
        'bg_soft': '#f5f3ff',
        'border_color': '#c4b5fd',
        'icon': 'bi-award-fill',
        'badge_bg': '#ede9fe',
        'badge_text': '#5b21b6',
    },
    'students': {
        'color': '#d97706',          # Warm Amber
        'bg_soft': '#fffbeb',
        'border_color': '#fcd34d',
        'icon': 'bi-people-fill',
        'badge_bg': '#fef3c7',
        'badge_text': '#92400e',
    },
    'centers': {
        'color': '#0284c7',          # Sky Blue
        'bg_soft': '#f0f9ff',
        'border_color': '#7dd3fc',
        'icon': 'bi-cpu-fill',
        'badge_bg': '#e0f2fe',
        'badge_text': '#075985',
    },
    'new_business': {
        'color': '#e11d48',          # Crimson / Rose
        'bg_soft': '#fff1f2',
        'border_color': '#fda4af',
        'icon': 'bi-lightning-charge-fill',
        'badge_bg': '#ffe4e6',
        'badge_text': '#9f1239',
    },
}

DEFAULT_CUSTOM_THEME = {
    'color': '#b45309',              # Dark Gold / Bronze
    'bg_soft': '#fffdf5',
    'border_color': '#fde68a',
    'icon': 'bi-folder-check',
    'badge_bg': '#fef3c7',
    'badge_text': '#78350f',
}


SESSION_STATUS = [
    ('draft',         'مسودة – تحضير'),
    ('publishing',    'منشورة – للاطلاع المسبق'),
    ('active',        'جارية – منعقدة'),
    ('partial_close', 'إغلاق جزئي – صياغة واعتماد القرارات'),
    ('frozen',        'مغلقة ومجمّدة'),
]

SESSION_STAGE_ORDER = ['draft', 'publishing', 'active', 'partial_close', 'frozen']

TOPIC_STATUS = [
    ('pending',    'مُدرج بجدول الأعمال'),
    ('discussing', 'قيد النقاش'),
    ('suspended',  'معلق مؤقتاً'),
    ('postponed',  'مؤجل'),
    ('voted',      'تم التصويت'),
    ('closed',     'مغلق'),
]

VOTE_CHOICES = [
    ('approve', 'موافق'),
    ('reject',  'مرفوض'),
    ('reserve', 'متحفظ'),
]

ATTENDANCE_STATUS = [
    ('present_primary', 'حاضر (أصيل)'),
    ('present_deputy',  'حاضر (إنابة)'),
    ('excused',         'غائب بعذر'),
    ('unexcused',       'غائب بغير عذر'),
    ('unrecorded',      'لم يُرصد بعد'),
    # للتوافقية القديمة
    ('present',         'حاضر'),
]


def user_can_view_drafts(user):
    """
    Check if user has permission to view draft sessions.
    Superusers, users with can_view_draft_sessions, stage managers, and session creators can view draft sessions.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_super', False):
        return True
    perm = user.get_permission() if hasattr(user, 'get_permission') else None
    return bool(
        perm and (
            getattr(perm, 'can_view_draft_sessions', False)
            or getattr(perm, 'can_advance_session_stage', False)
            or getattr(perm, 'can_add_session', False)
        )
    )


def user_can_view_past_sessions(user):
    """
    Check if user has permission to view previous council sessions (sessions prior to the latest session).
    Superusers and users with can_view_past_sessions permission can view previous sessions.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_super', False):
        return True
    perm = user.get_permission() if hasattr(user, 'get_permission') else None
    return bool(perm and getattr(perm, 'can_view_past_sessions', False))


# ── Council Session ────────────────────────────────────────────────────────────
class CouncilSession(models.Model):
    """Represents one council meeting/session with full 5-stage lifecycle."""
    session_number            = models.PositiveIntegerField('رقم الجلسة', unique=True)
    session_cumulative_number = models.PositiveIntegerField('الرقم التراكمي للجلسة', default=1,
                                                            help_text='مثال: 222')
    hijri_date                = models.CharField('التاريخ الهجري', max_length=60, blank=True,
                                                help_text='مثال: 15/2/1448هـ')
    chair_name                = models.CharField('رئيس المجلس', max_length=250, blank=True,
                                                default='الأستاذ الدكتور/ محمد أحمد البخيتي - رئيس الجامعة')
    secretary_name            = models.CharField('مقرر المجلس', max_length=250, blank=True,
                                                default='الأستاذ/ إسكندر عبده محمد المقالح - أمين عام الجامعة')
    assistant_name            = models.CharField('مساعد مقرر المجلس', max_length=250, blank=True,
                                                default='الأستاذ/ عبدالله عثمان محمد - مدير عام شؤون مجلس الجامعة')
    opening_honors            = models.TextField('المراسم الافتتاحية والتكريم', blank=True)
    title                     = models.CharField('عنوان الجلسة', max_length=300, blank=True)
    date                      = models.DateField('تاريخ الجلسة')
    time                      = models.TimeField('وقت بدء الجلسة', null=True, blank=True)
    end_time                  = models.TimeField('وقت إنهاء الجلسة', null=True, blank=True)
    location                  = models.CharField('مكان الانعقاد', max_length=300, blank=True,
                                                default='مبنى رئاسة الجامعة')
    academic_year             = models.CharField('السنة الأكاديمية', max_length=50, blank=True,
                                                help_text='مثال: 1448هـ - 2026/2027م')
    status                    = models.CharField('الحالة والمرحلة', max_length=20, choices=SESSION_STATUS, default='draft')
    agenda_notes              = models.TextField('ملاحظات جدول الأعمال', blank=True)
    custom_categories_json    = models.TextField('تصنيفات جدول الأعمال المخصصة', blank=True, default='')

    def get_agenda_categories(self):
        """
        Returns list of dicts:
        [{'key': 'general', 'label': 'المواضيع العامة', 'is_custom': False}, ...]
        """
        import json
        if self.custom_categories_json:
            try:
                data = json.loads(self.custom_categories_json)
                if isinstance(data, list) and len(data) > 0:
                    return data
            except Exception:
                pass
        return [
            {'key': k, 'label': l, 'is_custom': False}
            for k, l in TOPIC_CATEGORIES
        ]

    def set_agenda_categories(self, categories_list):
        """Saves category configuration as JSON."""
        import json
        self.custom_categories_json = json.dumps(categories_list, ensure_ascii=False)
        self.save(update_fields=['custom_categories_json'])

    def add_custom_category(self, label):
        """Adds a new custom category to this session."""
        import time
        cats = self.get_agenda_categories()
        clean_lbl = label.strip()
        key = f"c_{int(time.time()) % 1000000}"
        cats.append({'key': key, 'label': clean_lbl, 'is_custom': True})
        self.set_agenda_categories(cats)
        return key, clean_lbl

    def remove_agenda_category(self, key):
        """Removes/excludes a category from this session if it has no topics."""
        if self.topics.filter(category=key).exists():
            return False, "لا يمكن استبعاد عنوان رئيسي يحتوي على موضوعات مدرجة."
        cats = [c for c in self.get_agenda_categories() if c['key'] != key]
        self.set_agenda_categories(cats)
        return True, "تم استبعاد العنوان الرئيسي من جدول أعمال هذه الجلسة بنجاح."

    def restore_standard_category(self, key):
        """Restores a previously excluded standard category to this session's agenda."""
        cats = self.get_agenda_categories()
        if any(c['key'] == key for c in cats):
            return False, "هذا العنوان مدرج بالفعل في جدول أعمال الجلسة."
        standard_map = dict(TOPIC_CATEGORIES)
        if key not in standard_map:
            return False, "رمز العنوان غير صالح."
        cats.append({'key': key, 'label': standard_map[key], 'is_custom': False})
        self.set_agenda_categories(cats)
        return True, standard_map[key]

    # Lifecycle tracking fields
    frozen_at                 = models.DateTimeField('تاريخ التجميد', null=True, blank=True)
    frozen_by                 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='frozen_sessions', verbose_name='جمّدها'
    )
    stage_changed_at          = models.DateTimeField('آخر تغيير للمرحلة', null=True, blank=True)
    stage_changed_by          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stage_changed_sessions', verbose_name='غيّر المرحلة'
    )
    reopen_reason             = models.TextField('سبب إعادة الفتح', blank=True)
    last_active_topic         = models.ForeignKey(
        'Topic', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='آخر موضوع نشط في الجلسة'
    )

    # Live suspension / recess tracking (استراحة وتعليق مؤقت للجلسة الحية)
    is_suspended              = models.BooleanField('معلقة مؤقتاً (استراحة)', default=False)
    suspended_at              = models.DateTimeField('وقت تعليق الجلسة', null=True, blank=True)
    suspension_reason         = models.CharField('سبب التعليق / الاستراحة', max_length=255, blank=True)
    resumed_at                = models.DateTimeField('وقت استئناف الجلسة', null=True, blank=True)

    # Phase 3 Live Leadership & Dynamic Delegation (قيادة وتفويض إدارة الجلسة الحية)
    chair_user                = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='chaired_sessions', verbose_name='رئيس الجلسة (المستخدم)'
    )
    live_controller           = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='controlled_live_sessions', verbose_name='المتحكم المفوض بالجلسة الحية'
    )
    live_controller_delegated_at = models.DateTimeField('وقت تفويض الإدارة', null=True, blank=True)

    # بث عرض المحضر السابق على شاشات الأعضاء الحية
    broadcast_prev_minutes_session = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='broadcasted_in_sessions', verbose_name='المحضر السابق المعروض على الشاشات'
    )

    created_by                = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='created_sessions', verbose_name='أنشأها'
    )
    created_at                = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)
    updated_at                = models.DateTimeField('آخر تحديث', auto_now=True)

    # Phase 4: Cryptographic Hash & Read-Only Archiving
    document_hash             = models.CharField('البصمة الرقمية التشفيرية (SHA-256)', max_length=64, blank=True)
    hashed_at                 = models.DateTimeField('وقت توليد البصمة', null=True, blank=True)
    archived_pdf              = models.FileField('النسخة المؤرشفة للقراءة فقط (PDF)', upload_to='archived_sessions/', blank=True, null=True)

    class Meta:
        verbose_name = 'جلسة'
        verbose_name_plural = 'الجلسات'
        ordering = ['-date', '-session_number']

    def __str__(self):
        cum = f' ({self.session_cumulative_number})' if self.session_cumulative_number else ''
        return f'الجلسة رقم {self.session_number}{cum} – {self.date}'

    def get_chair_user(self):
        """Returns the User object representing the President/Chair of this session."""
        if self.chair_user_id:
            return self.chair_user
        try:
            from council.models import EntitySeat
            pres_seat = EntitySeat.objects.filter(seat_type='presidency', is_active=True).first()
            if pres_seat and pres_seat.primary_rep:
                return pres_seat.primary_rep
        except Exception:
            pass
        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        return UserModel.objects.filter(title='رئيس_الجامعة').first()

    def is_user_president(self, user):
        """Check if the given user is the President/Chair of this session."""
        if not user or not user.is_authenticated:
            return False
        chair = self.get_chair_user()
        if chair and chair.pk == user.pk:
            return True
        if getattr(user, 'title', None) == 'رئيس_الجامعة':
            return True
        return False

    def user_can_manage_live_controls(self, user):
        """
        Check if user is currently allowed to operate live session controls:
        1. President of the session ALWAYS has sovereign control.
        2. Delegated live_controller has active control granted by the President.
        3. Superuser has control only if no president is set/online and nobody is delegated.
        """
        if not user or not user.is_authenticated:
            return False
        if self.is_user_president(user):
            return True
        if self.live_controller_id and self.live_controller_id == user.pk:
            return True
        if getattr(user, 'is_super', False) and not self.live_controller_id:
            chair = self.get_chair_user()
            if not chair or chair.pk == user.pk:
                return True
        return False

    def get_chair_display_name(self):
        """Return clean display title for the session chair."""
        chair = self.get_chair_user()
        if chair:
            return chair.full_name
        return self.chair_name or 'رئيس المجلس'

    def get_stats(self):
        """Return quick stats for dashboard."""
        topics = list(self.topics.all())
        return {
            'total': len(topics),
            'voted': sum(1 for t in topics if t.status == 'voted'),
            'pending': sum(1 for t in topics if t.status == 'pending'),
        }

    def get_next_stage(self):
        """Return the next stage key or None if already frozen/closed."""
        try:
            # support legacy 'closed' status
            current = 'frozen' if self.status == 'closed' else self.status
            idx = SESSION_STAGE_ORDER.index(current)
            if idx < len(SESSION_STAGE_ORDER) - 1:
                return SESSION_STAGE_ORDER[idx + 1]
        except ValueError:
            pass
        return None

    def is_frozen(self):
        return self.status in ('frozen', 'closed')

    def is_past_session(self, user=None):
        """
        Check if this session is a previous session (strictly prior to the latest accessible session).
        Ordering is -date, -session_number.
        """
        qs = CouncilSession.objects.all()
        if user and not user_can_view_drafts(user):
            qs = qs.exclude(status='draft')
        latest = qs.order_by('-date', '-session_number').first()
        if not latest:
            return False
        return self.pk != latest.pk

    def can_be_seen_by(self, user):
        """Check if user can see this session (draft visibility and past session restriction)."""
        if not user or not user.is_authenticated:
            return False
        if getattr(user, 'is_super', False):
            return True
        if self.status == 'draft' and not user_can_view_drafts(user):
            return False
        if not getattr(user, 'can_view_past_sessions', False):
            if self.is_past_session(user):
                return False
        return True

    def get_status_color(self):
        colors = {
            'draft':         'secondary',
            'publishing':    'info',
            'active':        'success',
            'partial_close': 'warning',
            'frozen':        'danger',
            'closed':        'danger',
        }
        return colors.get(self.status, 'secondary')

    def get_status_icon(self):
        icons = {
            'draft':         '📝',
            'publishing':    '📢',
            'active':        '🟢',
            'partial_close': '🟠',
            'frozen':        '🔒',
            'closed':        '🔒',
        }
        return icons.get(self.status, '')

    def get_stage_steps(self):
        """Return list of (stage_key, stage_label) for lifecycle progress bar."""
        return [(k, v) for k, v in SESSION_STATUS]

    def get_quorum_info(self):
        """
        Calculates legal quorum: (total_active_seats // 2) + 1.
        Strictly counts active official EntitySeats (never exceeds total_seats / 100%).
        Takes into account approved ExitPermits (departed members).
        """
        from django.core.cache import cache
        cache_key = f"quorum_info_session_{self.pk}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        active_seats = list(EntitySeat.objects.filter(is_active=True).values(
            'id', 'primary_rep_id', 'deputy_rep_1_id', 'deputy_rep_2_id'
        ))
        total_seats = len(active_seats)
        if total_seats == 0:
            total_seats = 31  # 31 official seats
        quorum_required = (total_seats // 2) + 1

        valid_seat_ids = {s['id'] for s in active_seats}
        user_to_seat_id = {}
        for s in active_seats:
            for uid in (s['primary_rep_id'], s['deputy_rep_1_id'], s['deputy_rep_2_id']):
                if uid:
                    user_to_seat_id[uid] = s['id']

        present_attendances = self.attendances.filter(
            status__in=['present_primary', 'present_deputy', 'present']
        )
        departed_user_ids = set(
            self.exit_permits.filter(status='approved').values_list('member_id', flat=True)
        )
        departed_seat_ids = set(
            self.exit_permits.filter(status='approved', seat_id__isnull=False).values_list('seat_id', flat=True)
        )

        active_present_seats = set()
        for att in present_attendances:
            member_id = att.member_id
            if member_id in departed_user_ids or (att.proxy_user_id and att.proxy_user_id in departed_user_ids):
                continue
            seat_id = att.seat_id if att.seat_id in valid_seat_ids else (
                user_to_seat_id.get(member_id) or user_to_seat_id.get(att.proxy_user_id)
            )
            if seat_id and seat_id not in departed_seat_ids:
                active_present_seats.add(seat_id)

        present_count = min(len(active_present_seats), total_seats)
        is_achieved = present_count >= quorum_required
        missing_count = max(0, quorum_required - present_count)

        res = {
            'total_seats': total_seats,
            'quorum_required': quorum_required,
            'present_count': present_count,
            'is_achieved': is_achieved,
            'missing_count': missing_count,
            'quorum_percentage': round((present_count / total_seats) * 100, 1) if total_seats else 0,
        }
        cache.set(cache_key, res, 4)
        return res

    def get_present_members(self):
        """
        Returns list of members currently attending in this session.
        If formal attendance is recorded, strictly returns members marked present (excluding approved departures).
        If attendance has not yet been taken, falls back to active online session members or active council members.
        """
        departed_user_ids = set(
            self.exit_permits.filter(status='approved').values_list('member_id', flat=True)
        )
        present_atts = list(self.attendances.filter(
            status__in=['present_primary', 'present_deputy', 'present']
        ).select_related('member', 'proxy_user', 'seat'))

        members = []
        seen_user_ids = set()

        if present_atts:
            for att in present_atts:
                target_user = att.proxy_user if (att.is_proxy and att.proxy_user) else att.member
                if not target_user or target_user.pk in departed_user_ids or target_user.pk in seen_user_ids:
                    continue
                seen_user_ids.add(target_user.pk)
                seat_title = att.seat.name if att.seat else (target_user.department or '')
                members.append({
                    'id': target_user.pk,
                    'name': target_user.full_name,
                    'title': target_user.official_title or target_user.get_title_display(),
                    'seat_name': seat_title,
                    'avatar_initials': getattr(target_user, 'avatar_initials', '') or target_user.full_name[:2],
                    'is_proxy': att.is_proxy,
                    'proxy_name': att.proxy_name,
                })
        else:
            from accounts.models import User as CouncilUser
            cutoff = timezone.now() - timezone.timedelta(minutes=30)
            live_users = list(
                CouncilUser.objects.filter(
                    live_session_presences__session=self,
                    live_session_presences__last_seen__gte=cutoff,
                    live_session_presences__is_active=True
                ).exclude(pk__in=departed_user_ids).distinct()
            )
            if not live_users:
                live_users = list(
                    CouncilUser.objects.filter(is_active=True)
                    .exclude(title='مدير_النظام')
                    .exclude(pk__in=departed_user_ids)
                    .order_by('order', 'id')[:35]
                )
            for u in live_users:
                if u.pk in seen_user_ids:
                    continue
                seen_user_ids.add(u.pk)
                members.append({
                    'id': u.pk,
                    'name': u.full_name,
                    'title': u.official_title or u.get_title_display(),
                    'seat_name': u.department or '',
                    'avatar_initials': getattr(u, 'avatar_initials', '') or u.full_name[:2],
                    'is_proxy': False,
                    'proxy_name': '',
                })
        return members

    def get_live_active_topic(self):
        """Return the topic currently being discussed or voted on in live session."""
        active_state = TopicDisplayState.objects.filter(
            topic__session=self,
            display_status__in=['shown', 'voting']
        ).select_related('topic').first()
        if active_state:
            return active_state.topic
        return self.topics.first()

    def calculate_document_hash(self):
        """
        Computes SHA-256 cryptographic hash of session contents for tamper detection.
        Includes session identity, attendances, topics, decisions, tables, and dispatches.
        """
        import hashlib
        data_fragments = [
            f"SESSION:{self.session_number}:{self.session_cumulative_number}:{self.date}:{self.status}",
            f"CHAIR:{self.chair_name}|SEC:{self.secretary_name}",
        ]
        for att in self.attendances.order_by('member_id'):
            data_fragments.append(f"ATT:{att.member_id}:{att.status}:{att.is_proxy}")
        for t in self.topics.order_by('order_number', 'sub_order'):
            dec_text = t.decision.decision_text if hasattr(t, 'decision') and t.decision else ''
            signed_id = t.signed_decision.id if hasattr(t, 'signed_decision') and t.signed_decision else ''
            data_fragments.append(f"TOPIC:{t.order_number}:{t.category}:{t.title}|DEC:{dec_text}|SIGNED:{signed_id}")
            for tbl in t.tables.all():
                data_fragments.append(f"TBL:{tbl.id}:{tbl.title}:{len(tbl.rows_data)}")
        raw_string = "###".join(data_fragments)
        return hashlib.sha256(raw_string.encode('utf-8')).hexdigest()

    def verify_document_integrity(self):
        """Checks if current session state matches stored document_hash."""
        if not self.document_hash:
            return {'has_hash': False, 'is_valid': False, 'message': 'لم يتم توليد بصمة تشفيرية لهذه الجلسة بعد.'}
        current_hash = self.calculate_document_hash()
        is_valid = (current_hash == self.document_hash)
        return {
            'has_hash': True,
            'is_valid': is_valid,
            'stored_hash': self.document_hash,
            'current_hash': current_hash,
            'hashed_at': self.hashed_at,
            'message': 'المحضر سليم ومطابق تماماً للبصمة الرقمية المعتمدة ولم يطرأ عليه أي تعديل.' if is_valid else 'تنبيه أمني: البصمة الحالية لا تطابق البصمة المعتمدة عند الإغلاق!'
        }


# ── Session Stage Log ──────────────────────────────────────────────────────────
class SessionStageLog(models.Model):
    """Immutable record of every stage transition for a session."""
    session    = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='stage_logs', verbose_name='الجلسة'
    )
    from_stage = models.CharField('من المرحلة', max_length=30)
    to_stage   = models.CharField('إلى المرحلة', max_length=30)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='session_stage_changes', verbose_name='غيّرها'
    )
    changed_at = models.DateTimeField('وقت التغيير', auto_now_add=True)
    reason     = models.TextField('السبب والملاحظات', blank=True)

    class Meta:
        verbose_name = 'سجل مرحلة جلسة'
        verbose_name_plural = 'سجلات مراحل الجلسات'
        ordering = ['-changed_at']

    def __str__(self):
        return f'{self.session} | {self.from_stage} → {self.to_stage}'

    @property
    def to_stage_label(self):
        labels = dict(SESSION_STATUS)
        labels['published'] = 'منشورة – للاطلاع المسبق'
        return labels.get(self.to_stage, self.to_stage)

    @property
    def from_stage_label(self):
        labels = dict(SESSION_STATUS)
        labels['published'] = 'منشورة – للاطلاع المسبق'
        return labels.get(self.from_stage, self.from_stage)


# ── New Session Request (Previous Session Not Frozen) ──────────────────────────
class NewSessionRequest(models.Model):
    """Request to create a new session while previous session is not yet frozen."""
    STATUS_CHOICES = [
        ('pending',  'قيد المراجعة'),
        ('approved', 'موافق'),
        ('rejected', 'مرفوض'),
    ]
    previous_session = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='new_session_requests', verbose_name='الجلسة السابقة غير المجمّدة'
    )
    requested_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='requested_new_sessions', verbose_name='مقدم الطلب'
    )
    reason           = models.TextField('أسباب ومبررات فتح جلسة جديدة')
    status           = models.CharField('حالة الطلب', max_length=15, choices=STATUS_CHOICES, default='pending')
    reviewed_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_new_sessions', verbose_name='راجعه'
    )
    reviewed_at      = models.DateTimeField('تاريخ المراجعة', null=True, blank=True)
    review_notes     = models.TextField('ملاحظات رئيس الجامعة / المراجع', blank=True)
    used             = models.BooleanField('تم استخدام الموافقة لإنشاء الجلسة', default=False)
    created_at       = models.DateTimeField('تاريخ تقديم الطلب', auto_now_add=True)

    class Meta:
        verbose_name = 'طلب فتح جلسة جديدة'
        verbose_name_plural = 'طلبات فتح جلسات جديدة'
        ordering = ['-created_at']

    def __str__(self):
        return f'طلب فتح جلسة – {self.requested_by.full_name} ({self.get_status_display()})'


# ── System Audit & Backup Control ──────────────────────────────────────────────
class SystemAuditControl(models.Model):
    """
    Global configuration for Audit Logging and Automated Backup operations.
    Acts as a master switch to strictly pause or resume audit writes and automated backups.
    """
    is_enabled = models.BooleanField(
        'تفعيل تسجيل الرقابة والنسخ الاحتياطي',
        default=True,
        help_text='عند إلغاء التفعيل يتوقف النظام فوراً عن تسجيل حركات المستخدمين وأخذ النسخ الاحتياطية التلقائية'
    )
    updated_at = models.DateTimeField('تاريخ آخر تحديث', auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='حُدِّث بواسطة'
    )

    class Meta:
        verbose_name = 'إعدادات رقابة المستخدمين والنسخ الاحتياطي'
        verbose_name_plural = 'إعدادات رقابة المستخدمين والنسخ الاحتياطي'

    @classmethod
    def get_setting(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create(is_enabled=True)
        return obj

    @classmethod
    def is_audit_and_backup_active(cls):
        try:
            return cls.get_setting().is_enabled
        except Exception:
            return True


# ── Audit Log ──────────────────────────────────────────────────────────────────
class AuditLog(models.Model):
    """Immutable audit trail for all system events."""
    ACTION_CHOICES = [
        ('login',        'تسجيل دخول'),
        ('logout',       'تسجيل خروج'),
        ('create',       'إنشاء سجل'),
        ('update',       'تعديل بيانات'),
        ('delete',       'حذف سجل'),
        ('stage_change', 'نقل مرحلة الجلسة'),
        ('vote',         'تصويت'),
        ('permission',   'تخويل وتعديل صلاحيات'),
        ('export',       'تصدير مستند'),
        ('reopen',       'إعادة فتح جلسة مجمّدة'),
        ('reopen_fail',  'محاولة فاشلة لفتح جلسة'),
        ('request',      'تقديم طلب موافقة'),
        ('approve',      'موافقة على طلب'),
        ('reject',       'رفض طلب'),
        ('backup',       'نسخ احتياطي'),
    ]
    user          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs', verbose_name='المستخدم'
    )
    action        = models.CharField('نوع الإجراء', max_length=25, choices=ACTION_CHOICES)
    model_name    = models.CharField('النموذج / الجدول', max_length=100, blank=True)
    object_id     = models.CharField('معرِّف السجل', max_length=50, blank=True)
    object_repr   = models.CharField('وصف السجل', max_length=300, blank=True)
    field_changes = models.JSONField('التغييرات المسجلة', default=dict, blank=True)
    ip_address    = models.GenericIPAddressField('عنوان IP', null=True, blank=True)
    timestamp     = models.DateTimeField('التوقيت', auto_now_add=True)
    notes         = models.TextField('ملاحظات وتفاصيل إضافية', blank=True)

    class Meta:
        verbose_name = 'سجل رقابة'
        verbose_name_plural = 'سجل رقابة المستخدمين'
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        if not SystemAuditControl.is_audit_and_backup_active():
            return
        super().save(*args, **kwargs)

    def __str__(self):
        user_str = self.user.full_name if self.user else 'النظام'
        return f'[{self.timestamp:%Y-%m-%d %H:%M}] {user_str} – {self.get_action_display()} – {self.object_repr}'


# ── Backup Log ─────────────────────────────────────────────────────────────────
class BackupLog(models.Model):
    """Record of every automatic or manual database backup."""
    backup_path    = models.CharField('مسار ملف النسخة الاحتياطية', max_length=500)
    size_bytes     = models.PositiveBigIntegerField('الحجم (بايت)', default=0)
    created_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='backups_created', verbose_name='أنشأها'
    )
    created_at     = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)
    trigger_reason = models.CharField('سبب النسخ الاحتياطي', max_length=200, blank=True)
    success        = models.BooleanField('حالة النجاح', default=True)

    class Meta:
        verbose_name = 'نسخة احتياطية'
        verbose_name_plural = 'سجل النسخ الاحتياطية'
        ordering = ['-created_at']

    def get_size_display(self):
        if self.size_bytes < 1024:
            return f'{self.size_bytes} B'
        elif self.size_bytes < 1024 ** 2:
            return f'{self.size_bytes/1024:.1f} KB'
        return f'{self.size_bytes/(1024**2):.1f} MB'

    def __str__(self):
        return f'نسخة {self.created_at:%Y-%m-%d %H:%M} – {self.get_size_display()}'



# ── Entity Seat (مقاعد الجهات والممثلين) ───────────────────────────────────────
class EntitySeat(models.Model):
    """
    Represents an official faculty, presidency, or administrative council seat.
    Maps to primary representative (Dean/VP) and up to 2 proxy representatives.
    """
    SEAT_TYPES = [
        ('faculty',         'كلية'),
        ('presidency',      'رئاسة الجامعة'),
        ('vice_presidency', 'نيابة رئاسة الجامعة'),
        ('general_sec',     'الأمانة العامة'),
        ('advisory',        'المستشارون والمساعدون'),
        ('syndicate',       'نقابة أعضاء هيئة التدريس'),
        ('center',          'مركز / معهد'),
        ('other',           'جهة أخرى'),
    ]

    name         = models.CharField('اسم الجهة / الكلية / الإدارة', max_length=250, unique=True)
    seat_type    = models.CharField('نوع المقعد', max_length=30, choices=SEAT_TYPES, default='faculty')
    order        = models.PositiveIntegerField('الترتيب الهرمي بالمجلس', default=999)
    primary_rep  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='primary_seats', verbose_name='الممثل الأول (أصيل)'
    )
    deputy_rep_1 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deputy_1_seats', verbose_name='الممثل بالإنابة 1'
    )
    deputy_rep_2 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deputy_2_seats', verbose_name='الممثل بالإنابة 2'
    )
    is_active    = models.BooleanField('نشط', default=True)
    created_at   = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)
    updated_at   = models.DateTimeField('آخر تحديث', auto_now=True)

    class Meta:
        verbose_name = 'مقعد جهة'
        verbose_name_plural = 'مقاعد الجهات والكليات'
        ordering = ['order', 'name']

    def __str__(self):
        return f'{self.name} (ترتيب: {self.order})'

    def get_representatives(self):
        """Returns list of dicts with user info, role, role_label."""
        reps = []
        if self.primary_rep and self.primary_rep.is_active:
            reps.append({
                'id': self.primary_rep.id,
                'username': self.primary_rep.username,
                'full_name': self.primary_rep.full_name,
                'role': 'primary',
                'role_label': 'أصيل (الممثل الأول)',
                'title': self.primary_rep.official_title or self.primary_rep.get_title_display(),
                'is_primary': True,
            })
        if self.deputy_rep_1 and self.deputy_rep_1.is_active:
            reps.append({
                'id': self.deputy_rep_1.id,
                'username': self.deputy_rep_1.username,
                'full_name': self.deputy_rep_1.full_name,
                'role': 'deputy_1',
                'role_label': 'إنابة (الممثل الثاني)',
                'title': self.deputy_rep_1.official_title or self.deputy_rep_1.get_title_display(),
                'is_primary': False,
            })
        if self.deputy_rep_2 and self.deputy_rep_2.is_active:
            reps.append({
                'id': self.deputy_rep_2.id,
                'username': self.deputy_rep_2.username,
                'full_name': self.deputy_rep_2.full_name,
                'role': 'deputy_2',
                'role_label': 'إنابة (الممثل الثالث)',
                'title': self.deputy_rep_2.official_title or self.deputy_rep_2.get_title_display(),
                'is_primary': False,
            })
        return reps

    def has_user(self, user):
        """Check if user belongs to this seat (as primary or deputy)."""
        return user in (self.primary_rep, self.deputy_rep_1, self.deputy_rep_2)


# ── Session Read Receipt (إثبات الاطلاع المسبق) ──────────────────────────────
class SessionReadReceipt(models.Model):
    """
    مقترح 1 – علامة إثبات الاطلاع المسبق على جدول الأعمال وموضوعات الجلسة.
    """
    session         = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='read_receipts', verbose_name='الجلسة'
    )
    member          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='session_read_receipts', verbose_name='الممثل / العضو'
    )
    seat            = models.ForeignKey(
        EntitySeat, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='read_receipts', verbose_name='الجهة'
    )
    first_viewed_at = models.DateTimeField('وقت أول اطلاع', auto_now_add=True)
    ip_address      = models.GenericIPAddressField('عنوان IP', null=True, blank=True)

    class Meta:
        verbose_name = 'إثبات اطلاع مسبق'
        verbose_name_plural = 'سجلات إثبات الاطلاع المسبق'
        unique_together = ('session', 'member')
        ordering = ['-first_viewed_at']

    def __str__(self):
        return f'{self.member.full_name} – الجلسة {self.session.session_number} ({self.first_viewed_at:%Y-%m-%d %H:%M})'

# ── Attendance ─────────────────────────────────────────────────────────────────
class Attendance(models.Model):
    """Track member attendance for each session with 5 visual statuses and proxy support."""
    session               = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='attendances', verbose_name='الجلسة'
    )
    member                = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='attendances', verbose_name='العضو'
    )
    seat                  = models.ForeignKey(
        EntitySeat, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='attendances', verbose_name='المقعد / الجهة'
    )
    status                = models.CharField('الحضور', max_length=25, choices=ATTENDANCE_STATUS, default='unrecorded')
    is_proxy              = models.BooleanField('حضور بالإنابة', default=False)
    proxy_user            = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='proxy_attendances', verbose_name='الممثل الحاضر بالإنابة'
    )
    proxy_name            = models.CharField('اسم الممثل بالإنابة', max_length=200, blank=True)
    member_title_snapshot = models.CharField('الصفة في الجلسة', max_length=250, blank=True)
    notes                 = models.CharField('ملاحظات', max_length=300, blank=True)
    attended_at           = models.DateTimeField('وقت رصد الحضور', null=True, blank=True)
    auto_registered       = models.BooleanField('رصد آلي عند الدخول', default=False)

    class Meta:
        verbose_name = 'حضور'
        verbose_name_plural = 'الحضور والغياب'
        unique_together = ('session', 'member')
        ordering = ['member__order', 'member__full_name']

    def __str__(self):
        return f'{self.member.full_name} – {self.get_status_display()} – {self.session}'

    def get_status_badge_info(self):
        """Return dict with color, bg_class, badge_class, label for 5-color attendance visual."""
        s = self.status
        if s == 'present_primary' or (s == 'present' and not self.is_proxy):
            return {
                'color': '#28a745',
                'bg_class': 'bg-success',
                'badge_class': 'bg-success text-white',
                'label': 'حاضر (أصيل)',
                'icon_color': 'green',
                'category': 'primary',
            }
        elif s == 'present_deputy' or (s == 'present' and self.is_proxy):
            return {
                'color': '#fd7e14',
                'bg_class': 'bg-warning text-dark',
                'badge_class': 'bg-warning text-dark',
                'label': 'حاضر (إنابة)',
                'icon_color': 'orange',
                'category': 'deputy',
            }
        elif s == 'excused':
            return {
                'color': '#ffc107',
                'bg_class': 'bg-warning text-dark',
                'badge_class': 'bg-warning bg-opacity-25 text-dark border border-warning',
                'label': 'غائب بعذر',
                'icon_color': 'yellow',
                'category': 'excused',
            }
        elif s in ('unexcused', 'absent'):
            return {
                'color': '#dc3545',
                'bg_class': 'bg-danger text-white',
                'badge_class': 'bg-danger text-white',
                'label': 'غائب بلا عذر',
                'icon_color': 'red',
                'category': 'unexcused',
            }
        else:
            return {
                'color': '#6c757d',
                'bg_class': 'bg-secondary text-white',
                'badge_class': 'bg-secondary text-white',
                'label': 'لم يُرصد بعد',
                'icon_color': 'gray',
                'category': 'unrecorded',
            }


# ── Topic ──────────────────────────────────────────────────────────────────────
class Topic(models.Model):
    """A single agenda topic within a council session."""
    session           = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='topics', verbose_name='الجلسة'
    )
    category          = models.CharField('التصنيف', max_length=30, choices=TOPIC_CATEGORIES)
    sub_order         = models.PositiveIntegerField('الترتيب داخل التبويب', default=1,
                                                    help_text='الموضوع الأول، الثاني داخل التبويب')
    order_number      = models.PositiveIntegerField('الترتيب العام', default=1)
    title             = models.CharField('عنوان الموضوع', max_length=500)
    memo_number       = models.CharField('رقم المذكرة الواردة', max_length=100, blank=True)
    memo_date         = models.CharField('تاريخ المذكرة الواردة', max_length=100, blank=True)
    presenting_entity = models.CharField('الجهة العارضة', max_length=250, blank=True)
    target_seats      = models.ManyToManyField(
        'EntitySeat', blank=True,
        related_name='targeted_topics', verbose_name='الجهات والكليات المعنية بالموضوع'
    )
    background        = models.TextField('الحيثيات والخلفية')
    priorities        = models.TextField('الأولويات والمقترحات', blank=True)
    mentioned_persons = models.TextField(
        'الأشخاص المذكورون',
        blank=True,
        help_text='أدخل الأسماء مفصولة بفاصلة – تُستخدم في البحث'
    )
    status            = models.CharField('حالة الموضوع', max_length=20, choices=TOPIC_STATUS, default='pending')
    postponed_to      = models.CharField('جهة / موعد التأجيل', max_length=200, blank=True, help_text='مثال: الجلسة القادمة أو للجنة الشؤون الأكاديمية')
    postpone_reason   = models.TextField('سبب ومبرر التأجيل', blank=True)
    suspended_at      = models.DateTimeField('وقت التعليق المؤقت', null=True, blank=True)
    created_by        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='created_topics', verbose_name='أضافه'
    )
    created_at        = models.DateTimeField('تاريخ الإضافة', auto_now_add=True)
    updated_at        = models.DateTimeField('آخر تحديث', auto_now=True)

    class Meta:
        verbose_name = 'موضوع'
        verbose_name_plural = 'المواضيع'
        ordering = ['category', 'sub_order', 'order_number']

    def clean_fields(self, exclude=None):
        if exclude is None:
            exclude = []
        else:
            exclude = list(exclude)
        if 'category' not in exclude:
            exclude.append('category')
        super().clean_fields(exclude=exclude)

    def get_category_display(self):
        """Return human-readable label for standard or custom categories."""
        for k, v in TOPIC_CATEGORIES:
            if k == self.category:
                return v
        if hasattr(self, 'session') and self.session and hasattr(self.session, 'get_agenda_categories'):
            for cat in self.session.get_agenda_categories():
                if cat['key'] == self.category:
                    return cat['label']
        return self.category

    @property
    def category_theme(self):
        """Return the approved visual theme dict for this topic's category."""
        return CATEGORY_THEMES.get(self.category, DEFAULT_CUSTOM_THEME)

    @property
    def category_color(self):
        return self.category_theme['color']

    @property
    def category_icon(self):
        return self.category_theme['icon']

    @property
    def category_bg_soft(self):
        return self.category_theme['bg_soft']

    @property
    def category_border_color(self):
        return self.category_theme['border_color']

    @property
    def category_badge_bg(self):
        return self.category_theme['badge_bg']

    @property
    def category_badge_text(self):
        return self.category_theme['badge_text']

    def __str__(self):
        return f'{self.get_category_display()} – {self.title[:60]}'

    @classmethod
    def resequence_category(cls, session_id, category):
        """Ensure sub_order is strictly 1..N for all topics in (session_id, category)."""
        if not session_id or not category:
            return
        qs = list(cls.objects.filter(session_id=session_id, category=category).order_by('order_number', 'id'))
        updates = []
        for idx, topic in enumerate(qs, start=1):
            if topic.sub_order != idx:
                topic.sub_order = idx
                updates.append(topic)
        if updates:
            cls.objects.bulk_update(updates, ['sub_order'])

    @property
    def clean_priorities(self):
        """Return priorities without redundant 'القرار:' marker or if it's just a blank marker."""
        if not self.priorities:
            return ''
        import re
        norm = re.sub(r'[\u0640]', '', self.priorities.strip())
        if re.match(r'^[\s\-\*]*(?:ال+ق+رار|التوصيات)[\s\:\-\–]*$', norm):
            return ''
        clean = re.sub(r'^[\s\-\*]*(?:ال+ق+[\u0640]*رار|التوصيات)[\s\:\-\–]+', '', self.priorities.strip())
        return clean or self.priorities

    def save(self, *args, **kwargs):
        if self.priorities:
            import re
            norm = re.sub(r'[\u0640]', '', self.priorities.strip())
            if re.match(r'^[\s\-\*]*(?:ال+ق+رار|التوصيات)[\s\:\-\–]*$', norm):
                self.priorities = ''
            else:
                clean_prio = re.sub(r'^[\s\-\*]*(?:ال+ق+[\u0640]*رار|التوصيات)[\s\:\-\–]+', '', self.priorities.strip())
                if clean_prio:
                    self.priorities = clean_prio
        update_fields = kwargs.get('update_fields')
        old_category = None
        if self.pk and (update_fields is None or 'category' in update_fields):
            old_category = Topic.objects.filter(pk=self.pk).values_list('category', flat=True).first()
        super().save(*args, **kwargs)
        if update_fields is None or 'category' in update_fields or 'order_number' in update_fields or 'sub_order' in update_fields:
            self.resequence_category(self.session_id, self.category)
            if old_category and old_category != self.category:
                self.resequence_category(self.session_id, old_category)
            new_sub = Topic.objects.filter(pk=self.pk).values_list('sub_order', flat=True).first()
            if new_sub:
                self.sub_order = new_sub

    def delete(self, *args, **kwargs):
        session_id = self.session_id
        category = self.category
        res = super().delete(*args, **kwargs)
        self.resequence_category(session_id, category)
        return res

    @property
    def ordinal_label(self):
        """Return Arabic ordinal name with number for sub_order (e.g., الموضوع الأول (1))."""
        ordinals = {
            1: 'الموضوع الأول (1)',
            2: 'الموضوع الثاني (2)',
            3: 'الموضوع الثالث (3)',
            4: 'الموضوع الرابع (4)',
            5: 'الموضوع الخامس (5)',
            6: 'الموضوع السادس (6)',
            7: 'الموضوع السابع (7)',
            8: 'الموضوع الثامن (8)',
            9: 'الموضوع التاسع (9)',
            10: 'الموضوع العاشر (10)',
            11: 'الموضوع الحادي عشر (11)',
            12: 'الموضوع الثاني عشر (12)',
            13: 'الموضوع الثالث عشر (13)',
            14: 'الموضوع الرابع عشر (14)',
            15: 'الموضوع الخامس عشر (15)',
            16: 'الموضوع السادس عشر (16)',
            17: 'الموضوع السابع عشر (17)',
            18: 'الموضوع الثامن عشر (18)',
            19: 'الموضوع التاسع عشر (19)',
            20: 'الموضوع العشرون (20)',
            21: 'الموضوع الحادي والعشرون (21)',
            22: 'الموضوع الثاني والعشرون (22)',
            23: 'الموضوع الثالث والعشرون (23)',
            24: 'الموضوع الرابع والعشرون (24)',
            25: 'الموضوع الخامس والعشرون (25)',
            26: 'الموضوع السادس والعشرون (26)',
            27: 'الموضوع السابع والعشرون (27)',
            28: 'الموضوع الثامن والعشرون (28)',
            29: 'الموضوع التاسع والعشرون (29)',
            30: 'الموضوع الثلاثون (30)',
        }
        return ordinals.get(self.sub_order, f'الموضوع رقم ({self.sub_order})')

    def get_clear_status_display(self):
        """Return a clear, context-aware Arabic status label for council members."""
        if self.status == 'pending':
            if self.session_id and self.session.status == 'publishing':
                return 'مطروح للاطلاع المسبق'
            return 'مُدرج في جدول الأعمال'
        elif self.status == 'discussing':
            return 'قيد النقاش والمداولة'
        elif self.status == 'voted':
            return 'تم التصويت عليه'
        elif self.status == 'closed':
            return 'تم البت فيه'
        return self.get_status_display()

    def get_vote_summary(self):
        """Return vote counts for this topic (uses prefetched votes when available)."""
        votes = list(self.votes.all())
        return {
            'total':   len(votes),
            'approve': sum(1 for v in votes if v.choice == 'approve'),
            'reject':  sum(1 for v in votes if v.choice == 'reject'),
            'reserve': sum(1 for v in votes if v.choice == 'reserve'),
        }

    def has_decision(self):
        try:
            return self.decision is not None
        except Exception:
            return False

    def user_voted(self, user):
        """Check if a user already voted on this topic."""
        uid = getattr(user, 'pk', user)
        return any(v.member_id == uid for v in self.votes.all())

    def get_user_vote(self, user):
        """Get the user's vote object or None (uses prefetched votes when available)."""
        uid = getattr(user, 'pk', user)
        for v in self.votes.all():
            if v.member_id == uid:
                return v
        return None

    def get_display_state(self):
        """Get or create TopicDisplayState for this topic."""
        state, _ = TopicDisplayState.objects.get_or_create(topic=self)
        return state

    def is_voting_open(self):
        """Return True if voting is open by the Council President."""
        state = getattr(self, 'display_state', None)
        if not state:
            state = TopicDisplayState.objects.filter(topic=self).first()
        return state is not None and state.display_status == 'voting'


# ── Topic Attachment ───────────────────────────────────────────────────────────
class TopicAttachment(models.Model):
    """Files attached to a topic (scanned documents, PDFs, images)."""
    topic       = models.ForeignKey(
        Topic, on_delete=models.CASCADE,
        related_name='attachments', verbose_name='الموضوع'
    )
    file        = models.FileField('الملف', upload_to='attachments/%Y/%m/')
    file_name   = models.CharField('اسم الملف', max_length=300)
    file_type   = models.CharField('نوع الملف', max_length=10, blank=True)
    file_size   = models.PositiveIntegerField('الحجم (bytes)', default=0)
    description = models.CharField('وصف الملف', max_length=300, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='uploaded_attachments', verbose_name='رُفع بواسطة'
    )
    uploaded_at = models.DateTimeField('تاريخ الرفع', auto_now_add=True)

    class Meta:
        verbose_name = 'مرفق'
        verbose_name_plural = 'المرفقات'
        ordering = ['uploaded_at']

    def __str__(self):
        return self.file_name

    def save(self, *args, **kwargs):
        if self.file:
            if not self.file_name:
                self.file_name = self.file.name.split('/')[-1]
            ext = self.file_name.rsplit('.', 1)[-1].lower() if '.' in self.file_name else ''
            self.file_type = ext
            try:
                self.file_size = self.file.size
            except Exception:
                pass
        super().save(*args, **kwargs)

    def is_image(self):
        return self.file_type in ('jpg', 'jpeg', 'png', 'gif', 'webp')

    def is_pdf(self):
        return self.file_type == 'pdf'


# ── Topic Recording ────────────────────────────────────────────────────────────
class TopicRecording(models.Model):
    """Audio recording of the discussion for a topic."""
    topic              = models.ForeignKey(
        Topic, on_delete=models.CASCADE,
        related_name='recordings', verbose_name='الموضوع'
    )
    audio_file         = models.FileField('الملف الصوتي', upload_to='recordings/%Y/%m/')
    duration_seconds   = models.PositiveIntegerField('المدة (ثانية)', default=0)
    transcription_text = models.TextField('النص المُحوَّل', blank=True,
                                          help_text='يُملأ تلقائياً بواسطة Whisper AI')
    recorded_by        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='recordings', verbose_name='سجَّله'
    )
    recorded_at        = models.DateTimeField('تاريخ التسجيل', auto_now_add=True)
    label              = models.CharField('تسمية التسجيل', max_length=200, blank=True)

    class Meta:
        verbose_name = 'تسجيل صوتي'
        verbose_name_plural = 'التسجيلات الصوتية'
        ordering = ['recorded_at']

    def __str__(self):
        return f'تسجيل {self.topic.title[:40]} – {self.recorded_at.strftime("%Y-%m-%d %H:%M")}'

    def get_duration_display(self):
        m, s = divmod(self.duration_seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f'{h}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'


# ── Vote ───────────────────────────────────────────────────────────────────────
class Vote(models.Model):
    """A member's vote on a topic."""
    topic     = models.ForeignKey(
        Topic, on_delete=models.CASCADE,
        related_name='votes', verbose_name='الموضوع'
    )
    member    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='votes', verbose_name='العضو'
    )
    seat      = models.ForeignKey(
        EntitySeat, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='votes', verbose_name='المقعد / الجهة المصوتة'
    )
    is_proxy  = models.BooleanField('تصويت بالإنابة', default=False)
    choice    = models.CharField('القرار', max_length=10, choices=[
        ('approve', 'موافق'),
        ('reject',  'مرفوض'),
        ('reserve', 'متحفظ'),
    ])
    notes     = models.TextField('ملاحظات / سبب التحفظ أو الرفض', blank=True)
    voted_at  = models.DateTimeField('وقت التصويت', auto_now_add=True)
    updated_at = models.DateTimeField('آخر تحديث', auto_now=True)

    class Meta:
        verbose_name = 'تصويت'
        verbose_name_plural = 'التصويتات'
        unique_together = ('topic', 'member')
        ordering = ['voted_at']

    def __str__(self):
        return f'{self.member.full_name} – {self.get_choice_display()} – {self.topic.title[:40]}'

    def get_choice_icon(self):
        icons = {'approve': '✅', 'reject': '❌', 'reserve': '⚠️'}
        return icons.get(self.choice, '—')

    def get_choice_color(self):
        colors = {'approve': 'success', 'reject': 'danger', 'reserve': 'warning'}
        return colors.get(self.choice, 'secondary')


# ── Decision ───────────────────────────────────────────────────────────────────
class Decision(models.Model):
    """The final decision drafted for a topic."""
    topic              = models.OneToOneField(
        Topic, on_delete=models.CASCADE,
        related_name='decision', verbose_name='الموضوع'
    )
    decision_text      = models.TextField('نص القرار')
    ai_suggested_text  = models.TextField('مقترح الذكاء الاصطناعي', blank=True)
    drafted_by         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='drafted_decisions', verbose_name='صاغه'
    )
    drafted_at         = models.DateTimeField('تاريخ الصياغة', auto_now_add=True)
    updated_at         = models.DateTimeField('آخر تحديث', auto_now=True)

    class Meta:
        verbose_name = 'قرار'
        verbose_name_plural = 'القرارات'

    def __str__(self):
        return f'قرار: {self.topic.title[:60]}'

    @property
    def clean_text(self):
        """Returns the decision text stripped of redundant prefixes like 'القرار:'."""
        text = self.decision_text or ''
        import re
        clean = re.sub(r'^[\s\-\*]*(?:ال+ق+[\u0640]*رار|التوصيات)[\s\:\-\–]*', '', text).strip()
        return clean or text

    def save(self, *args, **kwargs):
        if self.decision_text:
            import re
            cleaned = re.sub(r'^[\s\-\*]*(?:ال+ق+[\u0640]*رار|التوصيات)[\s\:\-\–]*', '', self.decision_text.strip())
            if cleaned:
                self.decision_text = cleaned
        super().save(*args, **kwargs)


# ── Topic Table (Dynamic, Flexible & Math-enabled) ────────────────────────────
TABLE_PRESET_CHOICES = [
    ('custom',           'جدول مخصص (حر)'),
    ('appointment',      'جدول التعيينات'),
    ('confirmation',     'جدول التثبيت (تحت التجربة)'),
    ('settlement',       'جدول تسوية الوضع'),
    ('promotion',        'جدول الترقية العلمية'),
    ('hourly_contract',  'جدول التعاقد بنظام الساعات'),
    ('scopus_reward',    'جدول مكافآت نشر البحوث العلمية (Scopus)'),
    ('phd_defense',      'جدول اعتماد نتائج طلاب الدكتوراه'),
    ('master_defense',   'جدول اعتماد نتائج طلاب الماجستير'),
    ('diploma',          'جدول اعتماد نتائج الدبلومات'),
    ('graduates',        'جدول المصادقة واعتماد كشوفات الخريجين'),
    ('court_correction', 'جدول تعديل الشهادات بموجب أحكام المحاكم'),
    ('grade_correction', 'جدول تعديل وتصحيح النتائج والدرجات'),
]


class TopicTable(models.Model):
    """
    Dynamic smart table attached to a council Topic.
    Supports preset schemas, custom columns, live horizontal/vertical auto-sum, and record counter.
    """
    topic          = models.ForeignKey(
        Topic, on_delete=models.CASCADE,
        related_name='tables', verbose_name='الموضوع'
    )
    table_type     = models.CharField('نوع وقالب الجدول', max_length=40,
                                      choices=TABLE_PRESET_CHOICES, default='custom')
    title          = models.CharField('عنوان أو وصف الجدول', max_length=300, blank=True)
    headers        = models.JSONField('رؤوس الأعمدة', default=list, blank=True)
    rows_data      = models.JSONField('بيانات الصفوف', default=list, blank=True)
    sum_columns    = models.JSONField('أعمدة الجمع الرأسي التلقائي (أرقام الأعمدة)', default=list, blank=True)
    horizontal_sum = models.JSONField('إعدادات الجمع الأفقي', default=dict, blank=True)
    order          = models.PositiveIntegerField('ترتيب الجدول', default=1)
    notes          = models.TextField('ملاحظات إضافية', blank=True)

    class Meta:
        verbose_name = 'جدول الموضوع'
        verbose_name_plural = 'جداول الموضوعات'
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.title or self.get_table_type_display()} – ({self.topic.title[:30]})'

    def get_rows_count(self):
        """Count of records/rows in table."""
        return len(self.rows_data) if isinstance(self.rows_data, list) else 0

    def get_columns_count(self):
        """Count of columns in table."""
        return len(self.headers) if isinstance(self.headers, list) else 0

    def get_computed_totals(self):
        """Compute vertical totals for designated numeric columns."""
        if not self.headers or not self.rows_data or not self.sum_columns:
            return {}
        totals = {}
        for col_idx in self.sum_columns:
            try:
                col_i = int(col_idx)
            except (ValueError, TypeError):
                continue
            total = 0.0
            has_val = False
            for row in self.rows_data:
                if isinstance(row, list) and col_i < len(row):
                    val_str = str(row[col_i]).strip()
                    clean_val = ''.join(c for c in val_str if c.isdigit() or c in '.-')
                    if clean_val and clean_val not in ('.', '-'):
                        try:
                            total += float(clean_val)
                            has_val = True
                        except ValueError:
                            pass
            if has_val:
                totals[col_i] = int(total) if total.is_integer() else round(total, 2)
        return totals

    def get_formatted_total_row(self):
        """Returns a list corresponding to headers with total values and 'الإجمالي' label."""
        totals = self.get_computed_totals()
        if not totals or not self.headers:
            return None
        row = [''] * len(self.headers)
        if len(row) > 1:
            row[1] = 'الإجمالي'
        elif len(row) > 0:
            row[0] = 'الإجمالي'
        for col_idx, val in totals.items():
            if col_idx < len(row):
                header_text = str(self.headers[col_idx]) if col_idx < len(self.headers) else ''
                if 'دولار' in header_text or '$' in header_text:
                    row[col_idx] = f'{val:,}$'
                else:
                    row[col_idx] = f'{val:,}'
        return row


# ==============================================================================
# PHASE 3: LIVE SESSION, SPEAK REQUESTS, RECORDING & EXIT PERMITS
# ==============================================================================

# ── Topic Display State (Live Session Control) ───────────────────────────────
class TopicDisplayState(models.Model):
    """
    Controls live session display, folding, countdown timer, and voting state
    for a topic in real-time under the direct control of the Council President.
    """
    DISPLAY_STATUS_CHOICES = [
        ('hidden',    'مطوي / مخفي'),
        ('shown',     'معروض للنقاش (بدون تصويت)'),
        ('voting',    'مفتوح للتصويت'),
        ('suspended', 'معلق مؤقتاً (تخطي أثناء الانعقاد)'),
        ('closed',    'مغلق ومحسوب النتائج'),
    ]

    topic              = models.OneToOneField(
        Topic, on_delete=models.CASCADE,
        related_name='display_state', verbose_name='الموضوع'
    )
    display_status     = models.CharField(
        'حالة العرض والتصويت', max_length=20,
        choices=DISPLAY_STATUS_CHOICES, default='hidden'
    )
    allocated_minutes  = models.PositiveIntegerField(
        'الوقت المخصص بالدقائق', default=0,
        help_text='الوقت المخصص لمناقشة الموضوع (0 = بلا مؤقت زمني محدد)'
    )
    timer_started_at   = models.DateTimeField('وقت بدء المؤقت', null=True, blank=True)
    voting_opened_at   = models.DateTimeField('وقت فتح التصويت', null=True, blank=True)
    voting_closed_at   = models.DateTimeField('وقت إغلاق التصويت', null=True, blank=True)
    voting_opened_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='opened_votings', verbose_name='فُتح التصويت بواسطة'
    )
    voting_closed_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='closed_votings', verbose_name='أُغلق التصويت بواسطة'
    )

    class Meta:
        verbose_name = 'حالة عرض الموضوع'
        verbose_name_plural = 'حالات عرض المواضيع'

    def __str__(self):
        return f'{self.topic.title[:40]} – ({self.get_display_status_display()})'

    def get_remaining_seconds(self):
        """Calculate remaining seconds for countdown timer if set and running."""
        if not self.timer_started_at or self.allocated_minutes <= 0:
            return 0
        now = timezone.now()
        elapsed = (now - self.timer_started_at).total_seconds()
        total_sec = self.allocated_minutes * 60
        remaining = max(0, int(total_sec - elapsed))
        return remaining

    def get_vote_percentages(self):
        """Return breakdown and percentages of votes."""
        summary = self.topic.get_vote_summary()
        total = summary['total']
        if total == 0:
            return {
                'total': 0,
                'approve': 0, 'approve_pct': 0,
                'reject': 0,  'reject_pct': 0,
                'reserve': 0, 'reserve_pct': 0,
            }
        return {
            'total': total,
            'approve': summary['approve'],
            'approve_pct': round((summary['approve'] / total) * 100, 1),
            'reject': summary['reject'],
            'reject_pct': round((summary['reject'] / total) * 100, 1),
            'reserve': summary['reserve'],
            'reserve_pct': round((summary['reserve'] / total) * 100, 1),
        }


# ── Speak Request (Speech Queue) ──────────────────────────────────────────────
class SpeakRequest(models.Model):
    """
    Queue of members requesting to speak during session deliberation.
    Organized by request time and controlled by the Council President.
    """
    STATUS_CHOICES = [
        ('pending',   'في الانتظار'),
        ('speaking',  'يتحدث الآن'),
        ('completed', 'اكتملت المداخلة'),
        ('passed',    'تم التجاوز / اعتذر'),
        ('rejected',  'مرفوض'),
    ]

    session            = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='speak_requests', verbose_name='الجلسة'
    )
    topic              = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='speak_requests', verbose_name='الموضوع'
    )
    member             = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='speak_requests', verbose_name='العضو طالب الكلمة'
    )
    seat               = models.ForeignKey(
        EntitySeat, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='speak_requests', verbose_name='المقعد / الجهة'
    )
    requested_at       = models.DateTimeField('وقت طلب الكلمة', auto_now_add=True)
    status             = models.CharField('الحالة', max_length=20, choices=STATUS_CHOICES, default='pending')
    allowed_at         = models.DateTimeField('وقت الإذن بالحديث', null=True, blank=True)
    completed_at       = models.DateTimeField('وقت إنهاء المداخلة', null=True, blank=True)
    speak_start_offset = models.PositiveIntegerField(
        'ثانية بدء المداخلة في التسجيل', null=True, blank=True,
        help_text='بداية الحديث بالثواني من بداية التسجيل الصوتي للجلسة'
    )
    speak_end_offset   = models.PositiveIntegerField(
        'ثانية نهاية المداخلة في التسجيل', null=True, blank=True,
        help_text='نهاية الحديث بالثواني من بداية التسجيل الصوتي للجلسة'
    )
    notes              = models.CharField('ملاحظات', max_length=255, blank=True)

    class Meta:
        verbose_name = 'طلب مداخلة / كلمة'
        verbose_name_plural = 'طلبات المداخلات والكلمات'
        ordering = ['requested_at']

    def __str__(self):
        return f'{self.member.full_name} – طلب كلمة ({self.get_status_display()})'

    def get_duration_seconds(self):
        """Duration of this speech in seconds."""
        if self.speak_start_offset is not None and self.speak_end_offset is not None:
            return max(0, self.speak_end_offset - self.speak_start_offset)
        if self.allowed_at and self.completed_at:
            return int((self.completed_at - self.allowed_at).total_seconds())
        return 0


# ── Session Continuous Recording ──────────────────────────────────────────────
class SessionRecording(models.Model):
    """
    Continuous master audio recording of the entire council session.
    Supports in-browser recording with chunked uploads and time-offset indexing.
    """
    session               = models.OneToOneField(
        CouncilSession, on_delete=models.CASCADE,
        related_name='recording', verbose_name='الجلسة'
    )
    audio_file            = models.FileField(
        'ملف التسجيل الموحد', upload_to='session_recordings/%Y/%m/',
        null=True, blank=True
    )
    started_at            = models.DateTimeField('وقت بدء التسجيل', null=True, blank=True)
    ended_at              = models.DateTimeField('وقت إيقاف التسجيل', null=True, blank=True)
    duration_seconds      = models.PositiveIntegerField('إجمالي مدة التسجيل (ثانية)', default=0)
    is_paused             = models.BooleanField('متوقف مؤقتاً', default=False)
    paused_at             = models.DateTimeField('وقت التوقف المؤقت', null=True, blank=True)
    total_paused_seconds  = models.PositiveIntegerField('إجمالي ثواني التوقف المؤقت', default=0)
    chunk_count           = models.PositiveIntegerField('عدد الأجزاء المرفوعة', default=0)
    recorded_by           = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='session_recordings', verbose_name='المشرف على التسجيل'
    )
    created_at            = models.DateTimeField(auto_now_add=True)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تسجيل الجلسة الصوتي'
        verbose_name_plural = 'تسجيلات الجلسات الصوتية'

    def __str__(self):
        return f'تسجيل {self.session} – مدة: {self.get_duration_display()}'

    def get_duration_display(self):
        m, s = divmod(self.duration_seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f'{h:02d}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'


# ── Exit Permit (Formal Leave Request) ─────────────────────────────────────────
class ExitPermit(models.Model):
    """
    Formal exit permit request for a member wishing to depart the session permanently.
    Upon approval by the Council President, exit time is stamped and the seat is excluded
    from legal quorum and subsequent topic votings.
    """
    STATUS_CHOICES = [
        ('pending',  'قيد المراجعة'),
        ('approved', 'تم الإذن والمغادرة'),
        ('rejected', 'مرفوض – مستمر بالجلسة'),
    ]

    session      = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='exit_permits', verbose_name='الجلسة'
    )
    member       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='exit_permits', verbose_name='العضو طالب الإذن'
    )
    seat         = models.ForeignKey(
        EntitySeat, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='exit_permits', verbose_name='المقعد / الجهة'
    )
    requested_at = models.DateTimeField('وقت طلب الإذن', auto_now_add=True)
    reason       = models.TextField('سبب طلب المغادرة', blank=True)
    status       = models.CharField('الحالة', max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_exit_permits', verbose_name='البت بواسطة'
    )
    reviewed_at  = models.DateTimeField('تاريخ البت', null=True, blank=True)
    exit_time    = models.DateTimeField('وقت الخروج الفعلي', null=True, blank=True)

    class Meta:
        verbose_name = 'إذن مغادرة من القاعة'
        verbose_name_plural = 'أذونات المغادرة من القاعة'
        ordering = ['-requested_at']

    def __str__(self):
        return f'{self.member.full_name} – إذن خروج ({self.get_status_display()})'


# ── Live Session Presence (Manager Tracking & Dynamic Delegation) ────────────
class LiveSessionPresence(models.Model):
    """
    Tracks presence of operators / co-pilots connected to the live session cockpit.
    Allows the Council President to see who is present and selectively enable/freeze them.
    """
    session   = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='live_presences', verbose_name='الجلسة'
    )
    user      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='live_session_presences', verbose_name='المستخدم'
    )
    joined_at = models.DateTimeField('وقت الدخول', auto_now_add=True)
    last_seen = models.DateTimeField('آخر ظهور', auto_now=True)
    is_active = models.BooleanField('متصل حالياً', default=True)

    class Meta:
        verbose_name = 'حضور المشغل بالجلسة الحية'
        verbose_name_plural = 'سجل حضور المشغلين بالجلسات الحية'
        unique_together = ('session', 'user')
        ordering = ['-last_seen']

    def __str__(self):
        return f'{self.user.full_name} في {self.session}'


# ── Live Session Directive (Interactive Flash & Alert System) ─────────────────
class LiveSessionDirective(models.Model):
    """
    التوجيهات والتنبيهات التفاعلية المباشرة من رئاسة الجلسة إلى الأعضاء الحاضرين.
    يشمل:
    - نقطة نظام (Point of Order) مع وميض بصري فلاشي وصوت تنبيه متزامن.
    - يرجى الهدوء والتركيز (Calm & Focus Alert).
    - رسالة نصية مخصصة وموجهة باسم العضو.
    """
    DIRECTIVE_TYPES = [
        ('point_of_order', 'نقطة نظام'),
        ('calm_focus',     'يرجى الهدوء والتركيز'),
        ('custom_message', 'رسالة مخصصة'),
    ]

    session         = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='live_directives', verbose_name='الجلسة'
    )
    sender          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sent_live_directives', verbose_name='المرسِل'
    )
    recipient       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='received_live_directives', verbose_name='العضو المستهدف'
    )
    recipient_name  = models.CharField('اسم العضو المستهدف', max_length=200, blank=True)
    recipient_title = models.CharField('الصفة بالمجلس', max_length=255, blank=True)
    directive_type  = models.CharField('نوع التوجيه', max_length=30, choices=DIRECTIVE_TYPES)
    message         = models.TextField('نص التوجيه / الرسالة')
    is_read         = models.BooleanField('تم الاطلاع / الاستلام', default=False)
    read_at         = models.DateTimeField('وقت الاطلاع', null=True, blank=True)
    created_at      = models.DateTimeField('وقت الإرسال', auto_now_add=True)

    class Meta:
        verbose_name = 'توجيه تفاعلي بالجلسة'
        verbose_name_plural = 'التوجيهات التفاعلية بالجلسة الحية'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session', 'recipient', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f'{self.get_directive_type_display()} إلى {self.recipient.full_name} ({self.created_at:%H:%M:%S})'


# ==============================================================================
# PHASE 4: SIGNED DECISIONS, DISPATCH TO FACULTIES & DIGITAL HASH INTEGRITY
# ==============================================================================

class SignedDecisionAttachment(models.Model):
    """
    Official physically signed & stamped decision document (Scanned PDF or High-res Image)
    attached to a topic/decision after official approval.
    """
    topic           = models.OneToOneField(
        Topic, on_delete=models.CASCADE,
        related_name='signed_decision', verbose_name='الموضوع'
    )
    session         = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE,
        related_name='signed_decisions', verbose_name='الجلسة'
    )
    signed_file     = models.FileField(
        'ملف القرار الموقّع رسميًا (PDF / صورة)',
        upload_to='signed_decisions/%Y/%m/'
    )
    decision_number = models.CharField('رقم القرار الإداري الرسمي', max_length=100, blank=True)
    decision_date   = models.DateField('تاريخ توقيع القرار', null=True, blank=True)
    uploaded_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_signed_decisions', verbose_name='القائم بالرفع'
    )
    uploaded_at     = models.DateTimeField('وقت الرفع', auto_now_add=True)
    notes           = models.TextField('ملاحظات الأمانة العامة', blank=True)

    class Meta:
        verbose_name = 'مستند قرار موقّع'
        verbose_name_plural = 'مستندات القرارات الموقّعة'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'قرار موقّع: {self.topic.title[:50]} (جلسة {self.session.session_number})'

    def is_dispatched_to(self, seat):
        return self.dispatches.filter(seat=seat).exists()

    def get_dispatches_summary(self):
        total = self.dispatches.count()
        viewed = self.dispatches.filter(is_viewed=True).count()
        return {
            'total': total,
            'viewed': viewed,
            'pending': total - viewed,
        }


class SignedDecisionDispatch(models.Model):
    """
    Individual dispatch / delivery record of a signed decision to a specific official faculty seat.
    Ensures each faculty/entity sees only its relevant decisions, and tracks read receipts with IP & timestamp.
    """
    signed_decision = models.ForeignKey(
        SignedDecisionAttachment, on_delete=models.CASCADE,
        related_name='dispatches', verbose_name='القرار الموقّع'
    )
    seat            = models.ForeignKey(
        EntitySeat, on_delete=models.CASCADE,
        related_name='received_dispatches', verbose_name='الجهة المستلمة'
    )
    sent_by         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sent_dispatches', verbose_name='المرسِل'
    )
    sent_at         = models.DateTimeField('وقت الإرسال', auto_now_add=True)
    dispatch_notes  = models.CharField('توجيهات أو ملاحظات الإرسال', max_length=300, blank=True)

    # Read tracking
    is_viewed       = models.BooleanField('تم الاطلاع', default=False)
    viewed_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='viewed_dispatches', verbose_name='المطّلع'
    )
    viewed_at       = models.DateTimeField('وقت أول اطلاع', null=True, blank=True)
    view_count      = models.PositiveIntegerField('عدد مرات الاطلاع', default=0)
    ip_address      = models.GenericIPAddressField('عنوان IP للاطلاع', null=True, blank=True)

    class Meta:
        verbose_name = 'إرسال قرار لجهة'
        verbose_name_plural = 'سجلات إرسال القرارات للجهات'
        unique_together = ('signed_decision', 'seat')
        ordering = ['-sent_at']

    def __str__(self):
        return f'{self.signed_decision.topic.title[:30]} → {self.seat.name}'

    def mark_as_viewed(self, user, ip=None):
        if not self.is_viewed:
            self.is_viewed = True
            self.viewed_at = timezone.now()
            self.viewed_by = user
        self.view_count += 1
        if ip:
            self.ip_address = ip
        self.save(update_fields=['is_viewed', 'viewed_at', 'viewed_by', 'view_count', 'ip_address'])


# ── Phase 5: SMS Templates, In-App Notifications & Delivery Log ──────────────

class SMSTemplate(models.Model):
    """
    Standard customizable SMS message templates for council events.
    Supports variables: {name}, {session_num}, {date}, {time}, {topic_title}, {faculty_name}.
    """
    code          = models.CharField('رمز القالب', max_length=50, unique=True)
    title         = models.CharField('اسم القالب', max_length=150)
    template_text = models.TextField('نص القالب مع المتغيرات')
    is_active     = models.BooleanField('مفعّل', default=True)
    created_at    = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)
    updated_at    = models.DateTimeField('آخر تحديث', auto_now=True)

    class Meta:
        verbose_name = 'قالب رسائل SMS'
        verbose_name_plural = 'قوالب الرسائل النصية SMS'
        ordering = ['code']

    def __str__(self):
        return f'{self.title} ({self.code})'

    def format_message(self, **kwargs):
        """Safely formats the template string with provided kwargs."""
        text = self.template_text
        for key, val in kwargs.items():
            text = text.replace(f'{{{key}}}', str(val if val is not None else ''))
        return text


class InAppNotification(models.Model):
    """
    Instant user notifications shown in top bar notification bell and cockpits.
    """
    NOTIFICATION_CATEGORIES = [
        ('session_publishing', 'فتح الاطلاع المسبق'),
        ('session_live',       'بدء الجلسة الحية'),
        ('decision_dispatch',  'قرار موجه للجهة'),
        ('exit_permit',        'إذن مغادرة'),
        ('general',            'إشعار عام'),
    ]

    recipient  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='in_app_notifications', verbose_name='المستلم'
    )
    title      = models.CharField('عنوان التنبيه', max_length=200)
    message    = models.TextField('نص التنبيه')
    category   = models.CharField('نوع الإشعار', max_length=30, choices=NOTIFICATION_CATEGORIES, default='general')
    target_url = models.CharField('رابط الإجراء', max_length=300, blank=True)
    is_read    = models.BooleanField('تمت القراءة', default=False)
    read_at    = models.DateTimeField('وقت القراءة', null=True, blank=True)
    created_at = models.DateTimeField('تاريخ التنبيه', auto_now_add=True)

    class Meta:
        verbose_name = 'إشعار فوري'
        verbose_name_plural = 'الإشعارات الفورية داخل النظام'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f'{self.recipient.full_name} – {self.title[:30]}'

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class NotificationLog(models.Model):
    """
    Unified central delivery log for all SMS and In-App notifications sent by the system.
    """
    CHANNEL_CHOICES = [
        ('in_app', 'إشعار داخل النظام'),
        ('sms',    'رسالة نصية قصيرة SMS'),
        ('both',   'نظام و SMS'),
    ]
    STATUS_CHOICES = [
        ('sent',      'تم الإرسال'),
        ('simulated', 'محاكاة برمجية (سجل محلي)'),
        ('delivered', 'تم التسليم'),
        ('read',      'تم الاطلاع'),
        ('failed',    'تعذر الإرسال'),
    ]

    channel         = models.CharField('قناة التنبيه', max_length=20, choices=CHANNEL_CHOICES, default='in_app')
    recipient       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notification_logs', verbose_name='المستلم'
    )
    recipient_phone = models.CharField('رقم الهاتف', max_length=30, blank=True)
    recipient_name  = models.CharField('اسم المستلم', max_length=150, blank=True)
    session         = models.ForeignKey(
        CouncilSession, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notifications', verbose_name='الجلسة'
    )
    topic           = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notifications', verbose_name='الموضوع'
    )
    title           = models.CharField('عنوان الرسالة', max_length=200)
    message_body    = models.TextField('نص الرسالة / التنبيه')
    status          = models.CharField('حالة التسليم', max_length=20, choices=STATUS_CHOICES, default='sent')
    sent_by         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='dispatched_notifications', verbose_name='أرسلها'
    )
    sent_at         = models.DateTimeField('وقت الإرسال', auto_now_add=True)
    error_message   = models.TextField('ملاحظات أو رسالة الخطأ', blank=True)

    class Meta:
        verbose_name = 'سجل تسليم تنبيه'
        verbose_name_plural = 'سجل تسليم ومتابعة التنبيهات'
        ordering = ['-sent_at']

    def __str__(self):
        recip_str = self.recipient_name or (self.recipient.full_name if self.recipient else "جهة")
        return f'[{self.get_channel_display()}] {recip_str} – {self.title[:30]}'


# ---------------------------------------------------------------------------
# Phase 6: Smart Reader & Neural Cloud TTS (المقترح م7)
# ---------------------------------------------------------------------------

class SmartReaderSetting(models.Model):
    """
    Global / Administrative configuration for the Council Smart Audio Reader.
    Supports Cloud Neural voice and local Web Speech fallback.
    """
    VOICE_MODE_CHOICES = [
        ('cloud_neural', 'صوت عصبي عربي سحابي (Azure Neural)'),
        ('browser_local', 'صوت المتصفح المحلي (Web Speech)'),
    ]

    voice_mode      = models.CharField('نمط الصوت الافتراضي', max_length=30, choices=VOICE_MODE_CHOICES, default='cloud_neural')
    neural_voice    = models.CharField('اسم الصوت العصبي', max_length=100, default='ar-SA-HamedNeural')
    default_speed   = models.FloatField('السرعة الافتراضية', default=1.0)
    auto_scroll     = models.BooleanField('التمرير التلقائي مع القراءة', default=True)
    highlight_color = models.CharField('لون تمييز النص', max_length=30, default='#FEF08A')
    updated_at      = models.DateTimeField('آخر تحديث', auto_now=True)
    updated_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='حُدِّث بواسطة'
    )

    class Meta:
        verbose_name = 'إعدادات القراءة الذكية'
        verbose_name_plural = 'إعدادات القراءة الذكية'

    def __str__(self):
        return f'إعدادات القراءة الذكية ({self.get_voice_mode_display()})'

    @classmethod
    def get_settings(cls):
        """Return the active settings object or create default."""
        setting = cls.objects.first()
        if not setting:
            setting = cls.objects.create(
                voice_mode='cloud_neural',
                neural_voice='ar-SA-HamedNeural',
                default_speed=1.0,
                auto_scroll=True,
                highlight_color='#FEF08A'
            )
        return setting


class SmartReaderLog(models.Model):
    """
    Audit log tracking usage of the Smart Audio Reader during sessions/review.
    """
    user            = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='smart_reader_logs', verbose_name='المستخدم المستمع'
    )
    session         = models.ForeignKey(
        CouncilSession, on_delete=models.CASCADE, null=True, blank=True,
        related_name='smart_reader_logs', verbose_name='الجلسة'
    )
    topic           = models.ForeignKey(
        Topic, on_delete=models.CASCADE, null=True, blank=True,
        related_name='smart_reader_logs', verbose_name='الموضوع'
    )
    target_title    = models.CharField('المحتوى المقروء', max_length=300)
    voice_mode      = models.CharField('نمط الصوت', max_length=30, default='cloud_neural')
    speed           = models.FloatField('سرعة القراءة', default=1.0)
    chunks_count    = models.PositiveIntegerField('عدد الفقرات المقروءة', default=0)
    created_at      = models.DateTimeField('وقت الاستماع', auto_now_add=True)

    class Meta:
        verbose_name = 'سجل استخدام القراءة الذكية'
        verbose_name_plural = 'سجلات استخدام القراءة الذكية'
        ordering = ['-created_at']

    def __str__(self):
        u_name = self.user.full_name if self.user else "عضو مجلس"
        return f'{u_name} – {self.target_title[:30]} ({self.speed}x)'



