"""
Accounts Forms - University Council Management System
Forms for user authentication, management, smart permissions matrix, and member bulk import.
All labels and help texts are in Arabic.
"""
from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User, CouncilPermission


def _input(placeholder='', extra_class=''):
    return forms.TextInput(attrs={
        'class': f'form-control {extra_class}'.strip(),
        'placeholder': placeholder,
        'dir': 'auto',
    })


def _password_input(placeholder=''):
    return forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': placeholder,
        'autocomplete': 'new-password',
    })


def _email_input(placeholder=''):
    return forms.EmailInput(attrs={
        'class': 'form-control',
        'placeholder': placeholder,
        'dir': 'ltr',
    })


def _select_input():
    return forms.Select(attrs={'class': 'form-select'})


def _checkbox_input():
    return forms.CheckboxInput(attrs={'class': 'form-check-input'})


def _textarea_input(rows=3):
    return forms.Textarea(attrs={
        'class': 'form-control',
        'rows': rows,
        'dir': 'auto',
    })


# ─────────────────────────────────────────────────────────────────────────────
# 1. Login Form
# ─────────────────────────────────────────────────────────────────────────────
class LoginForm(forms.Form):
    username = forms.CharField(
        label='اسم المستخدم',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'اسم المستخدم',
            'autofocus': True,
            'dir': 'ltr',
            'autocomplete': 'username',
        }),
    )
    password = forms.CharField(
        label='كلمة المرور',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
        }),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self._user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        username = cleaned.get('username', '').strip()
        password = cleaned.get('password', '')

        if username and password:
            self._user_cache = authenticate(
                self.request, username=username, password=password
            )
            if self._user_cache is None:
                raise ValidationError('اسم المستخدم أو كلمة المرور غير صحيحة.')
            if not self._user_cache.is_active:
                raise ValidationError('هذا الحساب معطّل. يرجى مراجعة المسؤول.')
        return cleaned

    def get_user(self):
        return self._user_cache


# ─────────────────────────────────────────────────────────────────────────────
# Shared Seat & Category Assignment Mixin for User Create / Edit Forms
# ─────────────────────────────────────────────────────────────────────────────
class _SeatAssignmentFormMixin(forms.ModelForm):
    SEAT_MODE_CHOICES = [
        ('auto_seat',     'عضو مجلس صاحب مقعد رسمي مستقل (يُنشأ/يُحدّث له مقعد في هذه البوابة تلقائياً)'),
        ('existing_seat', 'ربط بمقعد جهة موجود مسبقاً (أصيل أو نائب بالإنابة)'),
        ('no_seat',       'حساب إداري / مستخدم مستقل (بدون مقعد تصويت في المجلس)'),
    ]
    SEAT_ROLE_CHOICES = [
        ('primary',  'الممثل الأول (الأصيل)'),
        ('deputy_1', 'الممثل بالإنابة الأول (نائب 1)'),
        ('deputy_2', 'الممثل بالإنابة الثاني (نائب 2)'),
    ]

    seat_mode = forms.ChoiceField(
        label='ارتباط العضو بمقاعد المجلس وشاشة الدخول',
        choices=SEAT_MODE_CHOICES,
        initial='auto_seat',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm', 'id': 'id_seat_mode'}),
    )
    existing_seat = forms.ModelChoiceField(
        label='مقعد الجهة / الكلية',
        queryset=None,
        required=False,
        empty_label='-- اختر مقعد الجهة أو الكلية --',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm', 'id': 'id_existing_seat'}),
    )
    seat_role = forms.ChoiceField(
        label='صفة التمثيل في المقعد',
        choices=SEAT_ROLE_CHOICES,
        initial='deputy_1',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm', 'id': 'id_seat_role'}),
    )

    def _init_seat_and_category_fields(self):
        from council.models import EntitySeat
        self.fields['existing_seat'].queryset = EntitySeat.objects.filter(is_active=True).order_by('order', 'name')
        if 'order' in self.fields:
            self.fields['order'].required = False
            if not self.instance or not self.instance.pk:
                self.fields['order'].initial = 999
        if 'login_category' in self.fields:
            self.fields['login_category'].required = False
            self.fields['login_category'].choices = User.LOGIN_CATEGORY_CHOICES

        if self.instance and self.instance.pk:
            self.fields['login_category'].initial = self.instance.get_effective_login_category()
            seat_info = self.instance.get_linked_seat_info()
            if seat_info and seat_info.get('seat'):
                seat = seat_info['seat']
                role = seat_info['role']
                self.fields['existing_seat'].initial = seat.pk
                self.fields['seat_role'].initial = role
                if role == 'primary':
                    self.fields['seat_mode'].initial = 'auto_seat'
                else:
                    self.fields['seat_mode'].initial = 'existing_seat'
            else:
                self.fields['seat_mode'].initial = 'no_seat'
        else:
            self.fields['login_category'].initial = 'deans'
            self.fields['seat_mode'].initial = 'auto_seat'

    def _clean_seat_and_category(self, cleaned):
        if not cleaned.get('order'):
            cleaned['order'] = self.instance.order if (self.instance and self.instance.pk and self.instance.order) else 999
        title_val = cleaned.get('title') or (self.instance.title if self.instance and self.instance.pk else 'اخرى')
        is_super_val = getattr(self.instance, 'is_super', False)
        if not cleaned.get('login_category'):
            cleaned['login_category'] = User.infer_category_from_title(title_val, is_super=is_super_val)
        seat_mode = cleaned.get('seat_mode')
        if seat_mode == 'existing_seat' and not cleaned.get('existing_seat'):
            self.add_error('existing_seat', 'يرجى اختيار مقعد الجهة أو الكلية المراد ربط العضو به.')
        return cleaned

    def save_seat_assignment(self, user):
        """Synchronize User.login_category and EntitySeat linkage according to admin selection."""
        from council.models import EntitySeat

        cat_key = self.cleaned_data.get('login_category') or user.get_effective_login_category()
        if user.login_category != cat_key:
            user.login_category = cat_key
            user.save(update_fields=['login_category'])

        # If form was submitted programmatically without seat_mode in POST data, only sync existing primary seat type
        if 'seat_mode' not in self.data:
            primary_seat = EntitySeat.objects.filter(primary_rep=user, is_active=True).first()
            if primary_seat:
                new_seat_type = User.category_to_seat_type(cat_key, user.title)
                if primary_seat.seat_type != new_seat_type:
                    primary_seat.seat_type = new_seat_type
                    primary_seat.save(update_fields=['seat_type', 'updated_at'])
            return

        seat_mode = self.cleaned_data.get('seat_mode') or 'no_seat'

        def _detach_user_from_all_seats(exclude_seat_id=None):
            qs = EntitySeat.objects.all()
            if exclude_seat_id:
                qs = qs.exclude(pk=exclude_seat_id)
            for s in qs.filter(primary_rep=user):
                s.primary_rep = None
                s.save(update_fields=['primary_rep', 'updated_at'])
            for s in qs.filter(deputy_rep_1=user):
                s.deputy_rep_1 = None
                s.save(update_fields=['deputy_rep_1', 'updated_at'])
            for s in qs.filter(deputy_rep_2=user):
                s.deputy_rep_2 = None
                s.save(update_fields=['deputy_rep_2', 'updated_at'])

        if seat_mode == 'no_seat':
            _detach_user_from_all_seats()
            return

        if seat_mode == 'existing_seat':
            target_seat = self.cleaned_data.get('existing_seat')
            role = self.cleaned_data.get('seat_role') or 'deputy_1'
            if target_seat:
                _detach_user_from_all_seats(exclude_seat_id=target_seat.pk)
                # Clear user from other slots on the same seat first
                if target_seat.primary_rep_id == user.id and role != 'primary':
                    target_seat.primary_rep = None
                if target_seat.deputy_rep_1_id == user.id and role != 'deputy_1':
                    target_seat.deputy_rep_1 = None
                if target_seat.deputy_rep_2_id == user.id and role != 'deputy_2':
                    target_seat.deputy_rep_2 = None

                if role == 'primary':
                    target_seat.primary_rep = user
                    target_seat.seat_type = User.category_to_seat_type(cat_key, user.title)
                elif role == 'deputy_1':
                    target_seat.deputy_rep_1 = user
                else:
                    target_seat.deputy_rep_2 = user

                target_seat.is_active = True
                target_seat.save()

                # Ensure user's login_category matches the linked seat's category
                seat_cat = User.seat_type_to_category(target_seat.seat_type)
                if user.login_category != seat_cat:
                    user.login_category = seat_cat
                    user.save(update_fields=['login_category'])
            return

        if seat_mode == 'auto_seat':
            target_seat_type = User.category_to_seat_type(cat_key, user.title)
            desired_name = (user.department or user.official_title or user.full_name).strip()
            existing_primary = EntitySeat.objects.filter(primary_rep=user).first()
            if existing_primary:
                _detach_user_from_all_seats(exclude_seat_id=existing_primary.pk)
                existing_primary.seat_type = target_seat_type
                if user.order and user.order != 999:
                    existing_primary.order = user.order
                if user.department and existing_primary.name != user.department.strip():
                    if not EntitySeat.objects.filter(name=user.department.strip()).exclude(pk=existing_primary.pk).exists():
                        existing_primary.name = user.department.strip()
                existing_primary.is_active = True
                existing_primary.save()
            else:
                _detach_user_from_all_seats()
                seat_by_name = EntitySeat.objects.filter(name=desired_name).first()
                if seat_by_name:
                    seat_by_name.primary_rep = user
                    seat_by_name.seat_type = target_seat_type
                    if user.order and user.order != 999:
                        seat_by_name.order = user.order
                    seat_by_name.is_active = True
                    seat_by_name.save()
                else:
                    base_name = desired_name or user.full_name
                    final_name = base_name
                    counter = 2
                    while EntitySeat.objects.filter(name=final_name).exists():
                        final_name = f"{base_name} ({counter})"
                        counter += 1
                    EntitySeat.objects.create(
                        name=final_name,
                        seat_type=target_seat_type,
                        order=user.order if (user.order and user.order != 999) else 999,
                        primary_rep=user,
                        is_active=True,
                    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. User Create Form (Manual Individual Creation)
# ─────────────────────────────────────────────────────────────────────────────
class UserCreateForm(_SeatAssignmentFormMixin):
    password1 = forms.CharField(
        label='كلمة المرور المؤقتة',
        initial='123456',
        widget=forms.PasswordInput(
            attrs={'class': 'form-control', 'placeholder': 'كلمة المرور الأولية (الافتراضية: 123456)', 'autocomplete': 'new-password'},
            render_value=True,
        ),
        help_text='كلمة المرور الافتراضية المبدئية هي 123456 (على الأقل 6 أحرف).',
    )
    password2 = forms.CharField(
        label='تأكيد كلمة المرور',
        initial='123456',
        widget=forms.PasswordInput(
            attrs={'class': 'form-control', 'placeholder': 'أعد كتابة كلمة المرور', 'autocomplete': 'new-password'},
            render_value=True,
        ),
    )

    class Meta:
        model = User
        fields = [
            'username', 'full_name', 'login_category', 'title', 'official_title',
            'department', 'order', 'phone', 'email', 'is_active', 'manager'
        ]
        labels = {
            'username':       'اسم المستخدم (باللغة الإنجليزية)',
            'full_name':      'الاسم الكامل واللقب الأكاديمي',
            'login_category': 'الموقع في مجلس الجامعة وبوابة الدخول',
            'official_title': 'الصفة الرسمية الكاملة بالمجلس (مع الكلية/الجهة)',
            'order':          'الترتيب بالمجلس',
            'title':          'اللقب الوظيفي / الصفة في المجلس',
            'department':     'الجهة / الكلية / الإدارة',
            'phone':          'رقم الهاتف',
            'email':          'البريد الإلكتروني',
            'is_active':      'الحساب نشط',
            'manager':        'المسؤول المباشر (اختياري)',
        }
        widgets = {
            'username':       forms.TextInput(attrs={'class': 'form-control', 'dir': 'ltr', 'placeholder': 'مثال: dean_eng'}),
            'full_name':      _input('مثال: أ.د. محمد عبدالله'),
            'login_category': forms.Select(attrs={'class': 'form-select', 'id': 'id_login_category'}),
            'official_title': _input('مثال: عميد كلية الشريعة والقانون'),
            'order':          forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '999'}),
            'title':          forms.Select(attrs={'class': 'form-select', 'id': 'id_title'}),
            'department':     _input('مثال: كلية الهندسة وتكنولوجيا المعلومات'),
            'phone':          forms.TextInput(attrs={'class': 'form-control', 'dir': 'ltr', 'placeholder': '777000000'}),
            'email':          _email_input('example@univ.edu'),
            'is_active':      _checkbox_input(),
            'manager':        _select_input(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_seat_and_category_fields()

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError('اسم المستخدم هذا مسجل مسبقاً.')
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'كلمتا المرور غير متطابقتين.')
        return self._clean_seat_and_category(cleaned)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
            # Initialize empty permissions (zero default)
            CouncilPermission.objects.get_or_create(user=user)
            self.save_seat_assignment(user)
        return user


# ─────────────────────────────────────────────────────────────────────────────
# 3. User Edit Form
# ─────────────────────────────────────────────────────────────────────────────
class UserEditForm(_SeatAssignmentFormMixin):
    class Meta:
        model = User
        fields = [
            'full_name', 'login_category', 'title', 'official_title',
            'department', 'order', 'phone', 'email', 'is_active', 'manager'
        ]
        labels = {
            'full_name':      'الاسم الكامل',
            'login_category': 'الموقع في مجلس الجامعة وبوابة الدخول',
            'official_title': 'الصفة الرسمية الكاملة بالمجلس (مع الكلية/الجهة)',
            'order':          'الترتيب بالمجلس',
            'title':          'اللقب الوظيفي / الصفة في المجلس',
            'department':     'الجهة / الكلية / الإدارة',
            'phone':          'رقم الهاتف',
            'email':          'البريد الإلكتروني',
            'is_active':      'الحساب نشط',
            'manager':        'المسؤول المباشر',
        }
        widgets = {
            'full_name':      _input('الاسم الثلاثي الكامل'),
            'login_category': forms.Select(attrs={'class': 'form-select', 'id': 'id_login_category'}),
            'official_title': _input('مثال: عميد كلية الشريعة والقانون'),
            'order':          forms.NumberInput(attrs={'class': 'form-control'}),
            'title':          forms.Select(attrs={'class': 'form-select', 'id': 'id_title'}),
            'department':     _input('الجهة أو الكلية'),
            'phone':          forms.TextInput(attrs={'class': 'form-control', 'dir': 'ltr'}),
            'email':          _email_input('example@univ.edu'),
            'is_active':      _checkbox_input(),
            'manager':        _select_input(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_seat_and_category_fields()

    def clean(self):
        cleaned = super().clean()
        return self._clean_seat_and_category(cleaned)

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            self.save_seat_assignment(user)
        return user


# ─────────────────────────────────────────────────────────────────────────────
# 4. Smart Permission Form (Granular Matrix + Groups)
# ─────────────────────────────────────────────────────────────────────────────
class PermissionForm(forms.ModelForm):
    """
    Comprehensive Smart Permission Matrix with 57 Granular Screen & Operation Permissions.
    Features:
      - Master Select All
      - Categorized Functional Groups (Screens & Buttons)
      - Notes and Audit
    """
    class Meta:
        model = CouncilPermission
        fields = CouncilPermission.ALL_PERMISSION_FIELDS + ['notes']
        widgets = {
            'notes': _textarea_input(rows=2),
        }

    # Structured metadata for template rendering (10 Functional Groups covering all Screens & Buttons)
    PERMISSION_GROUPS = [
        {
            'id': 'sessions',
            'title': 'شاشات وأزرار الجلسات ومحاضر الاجتماعات',
            'icon': 'bi-calendar3',
            'badge': 'الجلسات',
            'fields': [
                ('can_view_sessions', 'عرض شاشة الجلسات وتفاصيل الجلسة', 'الدخول إلى شاشة قائمة الجلسات واستعراض تفاصيل المحضر'),
                ('can_view_draft_sessions', 'عرض الجلسات في مرحلة التحضير (المسودة)', 'الاطلاع على الجلسات التي لا تزال في مرحلة المسودة والتحضير'),
                ('can_add_session', 'زر وشاشة إنشاء جلسة جديدة', 'إضافة جلسات جديدة لجدول المجلس ومواعيدها'),
                ('can_edit_session', 'زر وشاشة تعديل بيانات الجلسة', 'تعديل موعد أو مكان أو جدول أعمال الجلسة'),
                ('can_delete_session', 'زر حذف الجلسة', 'حذف الجلسة ومحضرها نهائياً'),
                ('can_view_attendance', 'عرض كشف الحضور والغياب في الجلسة', 'مشاهدة قائمة الحاضرين والغائبين في صفحة تفاصيل الجلسة'),
                ('can_manage_attendance', 'زر وشاشة إدارة ورصد الحضور والغياب', 'رصد وتعديل حضور وغياب وأعذار أعضاء المجلس'),
                ('can_export_minutes', 'زر تصدير المحضر إلى Word', 'تنزيل المحضر الرسمي منسقاً بصيغة .docx'),
                ('can_verify_integrity', 'زر فحص البصمة التشفيرية وتحميل PDF المؤرشف', 'فحص مطابقة البصمة الرقمية SHA-256 وتنزيل نسخة PDF الرسمية'),
            ]
        },
        {
            'id': 'topics',
            'title': 'شاشات وأزرار الموضوعات وجدول الأعمال',
            'icon': 'bi-journal-text',
            'badge': 'الموضوعات',
            'fields': [
                ('can_view_topics', 'عرض شاشة تفاصيل الموضوع والحيثيات والقرار', 'فتح صفحة الموضوع والاطلاع على الحيثيات والمقترحات والقرار'),
                ('can_add_topic', 'زر وشاشة إضافة موضوع جديد', 'إدراج موضوعات جديدة تحت التصنيفات المعتمدة'),
                ('can_edit_topic', 'زر وشاشة تعديل بيانات الموضوع', 'تعديل الحيثيات والأولويات والمقترحات'),
                ('can_delete_topic', 'زر حذف موضوع', 'حذف موضوع من جدول الأعمال'),
                ('can_change_topic_status', 'تغيير حالة الموضوع', 'تحديث حالة الموضوع (في الانتظار / قيد النقاش / تم التصويت / مغلق)'),
                ('can_import_topics', 'زر وشاشة استيراد مواضيع من Word', 'استخراج الموضوعات آلياً من ملفات Word'),
            ]
        },
        {
            'id': 'tables',
            'title': 'محرك الجداول الديناميكية والحسابات الآلية',
            'icon': 'bi-table',
            'badge': 'الجداول والحسابات',
            'fields': [
                ('can_add_table', 'زر وشاشة إضافة وبناء جداول البيانات', 'إنشاء جداول مخصصة أو استخدام القوالب الإحصائية الجاهزة'),
                ('can_edit_table', 'زر وشاشة تعديل الجداول والصفوف والحسابات', 'تعديل الأعمدة، لصق البيانات المجمعة، وضبط أعمدة الجمع التلقائي'),
                ('can_delete_table', 'زر حذف جداول البيانات', 'حذف الجداول التابعة للموضوع نهائياً'),
            ]
        },
        {
            'id': 'scanner',
            'title': 'أوليات ومرفقات الإسكانر (Scanner)',
            'icon': 'bi-paperclip',
            'badge': 'الأولويات والمرفقات',
            'fields': [
                ('can_view_attachments', 'زر معاينة وتحميل أوليات ومرفقات الموضوع', 'فتح وتنزيل ملفات PDF والصور والمستندات المرفقة بالموضوع'),
                ('can_upload_attachments', 'زر رفع أوليات ومستندات الإسكانر', 'إرفاق ملفات PDF وصور ووثائق ممسوحة ضوئياً'),
                ('can_delete_attachments', 'زر حذف المستندات المرفقة', 'حذف أوليات ومرفقات الموضوعات'),
            ]
        },
        {
            'id': 'audio',
            'title': 'التسجيلات الصوتية لنقاش القاعة والمواضيع',
            'icon': 'bi-mic-fill',
            'badge': 'التسجيلات الصوتية',
            'fields': [
                ('can_listen_audio', 'مشغل الاستماع وتحميل التسجيلات الصوتية', 'الاستماع إلى التسجيلات الصوتية للجلسة والمواضيع وتنزيلها'),
                ('can_record_audio', 'زر تسجيل نقاش الموضوع صوتياً', 'تشغيل ميكروفون القاعة وتسجيل مداولات الموضوع'),
                ('can_delete_audio', 'زر حذف التسجيلات الصوتية', 'حذف المقاطع الصوتية المسجلة'),
            ]
        },
        {
            'id': 'voting',
            'title': 'منظومة التصويت ونتائج الأصوات',
            'icon': 'bi-check2-square',
            'badge': 'التصويت',
            'fields': [
                ('can_vote', 'أزرار ممارسة حق التصويت (موافقة/رفض/تحفظ)', 'التصويت بالأزرار الثلاثة وإبداء الملاحظات والأسباب'),
                ('can_view_vote_details', 'زر مشاهدة تفاصيل أصوات الأعضاء وملاحظاتهم', 'استعراض قائمة أسماء المصوتين واختياراتهم وملاحظاتهم الفردية'),
            ]
        },
        {
            'id': 'decisions',
            'title': 'صياغة القرارات، التوقيع الرسمي، ومراسلات الكليات',
            'icon': 'bi-file-earmark-check',
            'badge': 'القرارات والمراسلات',
            'fields': [
                ('can_draft_decision', 'زر وشاشة صياغة واعتماد نص القرار', 'صلاحية صياغة أو تعديل القرار الرسمي للموضوع'),
                ('can_delete_decision', 'زر حذف القرار المعتمد', 'إلغاء وحذف نص القرار المعتمد'),
                ('can_upload_signed_decision', 'رفع مستند القرار الموقّع وتحديد الجهات المعنية', 'رفع ملف القرار الموقّع والمختوم وتحديد الكليات المستلمة'),
                ('can_send_decisions', 'زر إرسال وتعميم القرارات الموقَّعة إلى الجهات', 'إرسال وتعميم القرارات المعتمدة إلى صناديق مراسلات الكليات'),
                ('can_view_correspondence', 'شاشة مراسلات الكلية وتحميل القرارات الواردة', 'دخول شاشة مراسلات الكليات وتحميل القرارات المرسلة للجهة'),
                ('can_view_dispatch_log', 'شاشة سجل تعميم القرارات ومتابعة الاستلام', 'عرض سجل إرسال القرارات الموقعة ومعرفة الكليات التي اطلعت عليها'),
            ]
        },
        {
            'id': 'users_admin',
            'title': 'إدارة المستخدمين، الممثلين بالإنابة، والحساب',
            'icon': 'bi-shield-lock',
            'badge': 'المستخدمين والحساب',
            'fields': [
                ('can_manage_users', 'شاشة وأزرار إضافة وتعديل حسابات المستخدمين', 'عرض قائمة المستخدمين وإدخال وتعديل بياناتهم يدوياً'),
                ('can_delete_user', 'زر وشاشة حذف وتعطيل حسابات المستخدمين', 'السماح بحذف المستخدم نهائياً أو تعطيل حسابه مؤقتاً'),
                ('can_reset_user_password', 'زر وشاشة إعادة تعيين كلمات المرور للمستخدمين', 'السماح للمسؤول بإعادة تعيين وتصفير كلمة سر أي مستخدم في حال نسيانها'),
                ('can_import_members', 'شاشة وزر استيراد أعضاء المجلس (Excel/Word)', 'سحب واستيراد جداول الأعضاء دفعة واحدة'),
                ('can_grant_permissions', 'شاشة وزر تخويل وإدارة الصلاحيات', 'منح وتعديل الصلاحيات للمستخدمين في مصفوفة الصلاحيات'),
                ('can_manage_delegates', 'شاشة إدارة الممثلين بالإنابة (التفويض)', 'تحديد وتخويل نواب وممثلين بالإنابة عن الكلية أو الجهة'),
                ('can_change_password', 'شاشة وزر تغيير كلمة المرور', 'السماح للمستخدم بتغيير كلمة المرور الخاصة بحسابه'),
            ]
        },
        {
            'id': 'lifecycle_and_live',
            'title': 'دورة حياة الجلسة، الغرفة الحية (Live)، البروجكتر، والتحليلات',
            'icon': 'bi-broadcast',
            'badge': 'الجلسة الحية ومراحلها',
            'fields': [
                ('can_advance_session_stage', 'زر نقل الجلسة بين المراحل الخمس', 'نقل الجلسة بين مراحل التحضير، النشر، الانعقاد، الإغلاق الجزئي، والتجميد'),
                ('can_reopen_frozen_session', 'زر إعادة فتح الجلسة المجمّدة', 'إعادة فتح الجلسة بعد تجميدها مع التحقق الإلزامي من كلمة المرور والسبب'),
                ('can_approve_new_session', 'زر الموافقة على جلسة جديدة قبل إغلاق السابقة', 'البتّ في طلبات فتح جلسة جديدة في حال عدم تجميد الجلسة السابقة'),
                ('can_view_live_session', 'دخول شاشة غرفة الجلسة الحية (Live)', 'الدخول إلى قاعة الجلسة الحية التفاعلية ومتابعة النقاش اللحظي'),
                ('can_start_session_live', 'أزرار إدارة الجلسة الحية وفتح/إغلاق التصويت', 'التحكم بعرض/طي المواضيع وفتح وإنهاء التصويت في الجلسة الحية'),
                ('can_set_topic_timer', 'زر ضبط وقت المواضيع وتمديده وإيقافه', 'تحديد المؤقت الزمني لمناقشة كل موضوع في الجلسة الحية'),
                ('can_manage_speak_requests', 'أزرار إدارة طابور المداخلات (سماح/تجاوز/إنهاء)', 'السماح للأعضاء بالتحدث، تجاوز الدور، وإنهاء المداخلات'),
                ('can_request_speak', 'زر طلب الكلمة والمداخلة في الجلسة الحية', 'إمكانية طلب الكلمة والمداخلة أثناء انعقاد الجلسة الحية'),
                ('can_control_recording', 'أزرار التحكم في التسجيل الصوتي للجلسة الحية', 'بدء وإيقاف واستئناف وإنهاء التسجيل الصوتي الشامل للجلسة'),
                ('can_request_exit_permit', 'زر طلب الإذن بالمغادرة النهائية من الجلسة', 'إرسال طلب إذن بالخروج النهائي من القاعة لرئيس المجلس'),
                ('can_approve_exit_permit', 'أزرار البتّ في طلبات الإذن بالمغادرة', 'الموافقة على طلبات مغادرة الأعضاء أو رفضها'),
                ('can_view_projector', 'عرض شاشة القاعة البروجكتر (Projector)', 'فتح شاشة العرض الكبيرة المخصصة لقاعة الاجتماع'),
                ('can_view_analytics', 'عرض شاشة التقرير التحليلي للجلسة', 'استعراض الإحصائيات التحليلية لأداء الجلسة والمداخلات والتصويت'),
            ]
        },
        {
            'id': 'search_and_system',
            'title': 'شاشات البحث، التنبيهات، القراءة الذكية، وسجل الرقابة',
            'icon': 'bi-search',
            'badge': 'البحث والنظام',
            'fields': [
                ('can_search_minutes', 'شاشة البحث الشامل في المحاضر والمواضيع', 'استخدام محرك البحث النصي في الموضوعات والقرارات والتصويتات'),
                ('can_search_person', 'شاشة البحث عن شخص / مستفيد', 'البحث عن أسماء الأشخاص والمستفيدين عبر كافة المحاضر'),
                ('can_view_notifications', 'جرس ومركز التنبيهات والإشعارات', 'مشاهدة جرس الإشعارات العلوي وفتح شاشة مركز التنبيهات'),
                ('can_view_notification_log', 'شاشة سجل تسليم التنبيهات ورسائل SMS', 'الاطلاع على سجل إرسال الإشعارات والرسائل النصية للأعضاء'),
                ('can_manage_sms_template', 'شاشة إعداد قوالب الرسائل النصية (SMS)', 'إدارة وتعديل قوالب التبليغ النصي للأعضاء'),
                ('can_use_smart_reader', 'زر تشغيل القراءة الذكية للمحاضر والمواضيع', 'تشغيل محرك القراءة الصوتية الفصيحة والمزامنة البصرية للمحاضر والمواضيع'),
                ('can_manage_smart_reader', 'شاشة إعدادات وسجل القراءة الذكية', 'إدارة إعدادات الصوت والسرعة والاطلاع على سجل استخدام القارئ الذكي'),
                ('can_view_audit_log', 'شاشة سجل رقابة المستخدمين والنسخ الاحتياطي', 'الاطلاع على السجل الشامل لعمليات وتعديلات النظام'),
            ]
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Member Bulk Import Form (Excel / Word)
# ─────────────────────────────────────────────────────────────────────────────
class MemberImportForm(forms.Form):
    import_file = forms.FileField(
        label='ملف أعضاء المجلس (Excel أو Word)',
        help_text='الملفات المدعومة: .xlsx, .xls, .csv, .docx',
        widget=forms.FileInput(attrs={
            'class': 'form-control form-control-lg',
            'accept': '.xlsx,.xls,.csv,.docx',
            'id': 'import_file_input',
        })
    )
    default_category = forms.ChoiceField(
        label='الموقع الافتراضي في مجلس الجامعة وبوابة الدخول (إذا لم يكن محدداً بالملف)',
        choices=User.LOGIN_CATEGORY_CHOICES,
        initial='deans',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_default_category'}),
    )
    default_title = forms.ChoiceField(
        label='الصفة الافتراضية في المجلس (إذا لم تكن محددة بالملف)',
        choices=User.TITLE_CHOICES,
        initial='عميد',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_default_title'}),
    )
    auto_create_seats = forms.BooleanField(
        label='إنشاء/تحديث مقاعد رسمية تلقائياً للأعضاء المستوردين في شاشة الدخول',
        required=False,
        initial=True,
        widget=_checkbox_input(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Change Password Form
# ─────────────────────────────────────────────────────────────────────────────
class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(
        label='كلمة المرور الحالية',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '••••••••'}),
    )
    new_password1 = forms.CharField(
        label='كلمة المرور الجديدة',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '••••••••'}),
    )
    new_password2 = forms.CharField(
        label='تأكيد كلمة المرور الجديدة',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '••••••••'}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        # Backward/template compatibility: alias fields if present in POST data
        data = kwargs.get('data')
        if data is not None:
            if hasattr(data, 'copy'):
                data = data.copy()
            else:
                data = dict(data)
            if 'old_password' in data and not data.get('current_password'):
                data['current_password'] = data['old_password']
            if 'new_password' in data and not data.get('new_password1'):
                data['new_password1'] = data['new_password']
            if 'confirm_password' in data and not data.get('new_password2'):
                data['new_password2'] = data['confirm_password']
            kwargs['data'] = data
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        current = self.cleaned_data.get('current_password')
        if not self.user.check_password(current):
            raise ValidationError('كلمة المرور الحالية غير صحيحة.')
        return current

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('new_password1')
        p2 = cleaned.get('new_password2')
        if p1 and p2:
            if p1 != p2:
                self.add_error('new_password2', 'كلمتا المرور الجديدتان غير متطابقتين.')
            validate_password(p1, user=self.user)
        return cleaned

    def save(self):
        self.user.set_password(self.cleaned_data['new_password1'])
        if self.user.pk:
            self.user.save(update_fields=['password'])
        else:
            self.user.save()
        return self.user


# ─────────────────────────────────────────────────────────────────────────────
# 7. Admin Reset User Password Form
# ─────────────────────────────────────────────────────────────────────────────
class AdminResetPasswordForm(forms.Form):
    new_password = forms.CharField(
        label='كلمة المرور الجديدة',
        initial='123456',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'أدخل كلمة المرور الجديدة',
            'autocomplete': 'new-password'
        }, render_value=True),
        help_text='الافتراضية: 123456 (يمكنك تعيين أي كلمة مرور جديدة).'
    )
    confirm_password = forms.CharField(
        label='تأكيد كلمة المرور',
        initial='123456',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'أعد كتابة كلمة المرور للتأكيد',
            'autocomplete': 'new-password'
        }, render_value=True),
    )

    def __init__(self, target_user=None, *args, **kwargs):
        if target_user is None:
            target_user = kwargs.pop('user', None) or kwargs.pop('target_user', None)
        self.target_user = target_user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('new_password')
        p2 = cleaned.get('confirm_password')
        if p1 and p2:
            if p1 != p2:
                self.add_error('confirm_password', 'كلمتا المرور غير متطابقتين.')
            if len(p1) < 6:
                self.add_error('new_password', 'يجب ألا تقل كلمة المرور عن 6 أحرف.')
        return cleaned

    def save(self):
        new_pwd = self.cleaned_data['new_password']
        self.target_user.set_password(new_pwd)
        if self.target_user.pk:
            self.target_user.save(update_fields=['password'])
        else:
            self.target_user.save()
        return self.target_user
