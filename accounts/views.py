"""
Accounts Views - University Council Management System
Handles authentication, user management, permissions, and the main dashboard.

Access control is enforced via two decorators:
  - login_required_custom  → redirects to /login/ if not authenticated
  - permission_required_custom(perm) → checks a named perm on request.user
"""
import functools

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    ChangePasswordForm,
    LoginForm,
    PermissionForm,
    UserCreateForm,
    UserEditForm,
)
from .models import CouncilPermission, User
from council.audit import log_action


# ═════════════════════════════════════════════════════════════════════════════
# Access-Control Decorators
# ═════════════════════════════════════════════════════════════════════════════

def login_required_custom(view_func):
    """
    Decorator: redirect anonymous users to /login/.
    Stores the originally requested URL in `next` query param.
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            next_url = request.get_full_path()
            return redirect(f'/login/?next={next_url}')
        return view_func(request, *args, **kwargs)
    return wrapper


def permission_required_custom(perm):
    """
    Decorator factory: verify that the authenticated user holds `perm`.

    `perm` must be one of:
        'is_super' | 'can_add' | 'can_edit' | 'can_delete' |
        'can_vote' | 'can_draft' | 'can_grant'

    Super Admins bypass all checks automatically (handled in model properties).
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        @login_required_custom          # ensure login first
        def wrapper(request, *args, **kwargs):
            user = request.user
            # 'is_super' check
            if perm == 'is_super' and not user.is_super:
                messages.error(request, 'هذه العملية مخصصة للمسؤول الأعلى فقط.')
                return redirect('/dashboard/')
            # property-based perm check (can_add, can_grant, …)
            elif perm != 'is_super':
                if not getattr(user, perm, False):
                    messages.error(request, 'ليس لديك صلاحية للوصول إلى هذه الصفحة.')
                    return redirect('/dashboard/')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# ═════════════════════════════════════════════════════════════════════════════
# Helper: get client IP
# ═════════════════════════════════════════════════════════════════════════════

def _get_client_ip(request):
    """Extract the real client IP from request headers."""
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


# ═════════════════════════════════════════════════════════════════════════════
# Authentication Views
# ═════════════════════════════════════════════════════════════════════════════

def _handle_auto_attendance_and_receipts(user, seat, request):
    """
    Auto registers attendance and read receipts upon login (م5, م6, مقترح 1, مقترح 9).
    """
    from council.models import CouncilSession, Attendance, SessionReadReceipt, EntitySeat
    if not seat:
        seat = EntitySeat.objects.filter(
            Q(primary_rep=user) | Q(deputy_rep_1=user) | Q(deputy_rep_2=user),
            is_active=True
        ).first()

    if not seat:
        return

    is_proxy = (seat.primary_rep != user)
    official_member = seat.primary_rep if seat.primary_rep else user

    # 1. Auto attendance for active/publishing/partial_close sessions
    active_sessions = CouncilSession.objects.filter(status__in=['active', 'publishing', 'partial_close'])
    for s in active_sessions:
        att, created = Attendance.objects.get_or_create(
            session=s,
            member=official_member,
            defaults={
                'seat': seat,
                'status': 'present_primary' if not is_proxy else 'present_deputy',
                'is_proxy': is_proxy,
                'proxy_user': user if is_proxy else None,
                'proxy_name': user.full_name if is_proxy else '',
                'auto_registered': True,
                'attended_at': timezone.now(),
                'member_title_snapshot': official_member.official_title or official_member.get_title_display(),
            }
        )
        if not created:
            if att.status in ('unrecorded', 'unexcused', 'excused', 'absent') or not att.auto_registered:
                att.seat = seat
                att.status = 'present_primary' if not is_proxy else 'present_deputy'
                att.is_proxy = is_proxy
                att.proxy_user = user if is_proxy else None
                att.proxy_name = user.full_name if is_proxy else ''
                att.auto_registered = True
                att.attended_at = timezone.now()
                att.save(update_fields=['seat', 'status', 'is_proxy', 'proxy_user', 'proxy_name', 'auto_registered', 'attended_at'])

    # 2. Read Receipt for publishing sessions (مقترح 1)
    for pub_s in CouncilSession.objects.filter(status='publishing'):
        SessionReadReceipt.objects.get_or_create(
            session=pub_s,
            member=user,
            defaults={
                'seat': seat,
                'ip_address': _get_client_ip(request)
            }
        )


def _get_seat_category_key(seat_type, primary_rep=None):
    """Map EntitySeat to one of the 5 main login screen categories, respecting primary_rep.login_category if set."""
    valid_keys = dict(User.LOGIN_CATEGORY_CHOICES)
    if primary_rep and getattr(primary_rep, 'login_category', '') in valid_keys:
        return primary_rep.login_category
    if seat_type in ('presidency', 'advisory'):
        return 'presidency_office'
    elif seat_type == 'vice_presidency':
        return 'vice_presidents'
    elif seat_type == 'faculty':
        return 'deans'
    elif seat_type == 'general_sec':
        return 'secretariat_admin'
    return 'representatives'


def _get_user_category_key(user):
    """Map a standalone User (not linked to an EntitySeat) to one of the 5 categories."""
    return user.get_effective_login_category()


def login_view(request):
    """
    Display categorized institutional login or direct login, and authenticate user.
    Supports smart modal popup for single/multiple representatives with individual passwords.
    On success: auto-registers attendance and read receipts, records audit log.
    """
    if request.user.is_authenticated:
        return redirect('/dashboard/')

    import json
    from council.models import EntitySeat
    from .models import compute_avatar_initials

    next_url = request.GET.get('next', '/dashboard/')
    form = LoginForm(request=request)
    seats = (
        EntitySeat.objects.filter(is_active=True)
        .select_related('primary_rep', 'deputy_rep_1', 'deputy_rep_2')
        .order_by('order', 'name')
    )
    failed_state = None

    if request.method == 'POST':
        login_type = request.POST.get('login_type', 'direct')

        if login_type == 'entity':
            seat_id  = request.POST.get('seat_id')
            user_id  = request.POST.get('user_id')
            password = request.POST.get('password', '')

            seat = EntitySeat.objects.filter(pk=seat_id, is_active=True).first()
            selected_user = User.objects.filter(pk=user_id, is_active=True).first()

            if not seat or not selected_user or not seat.has_user(selected_user):
                err_msg = 'يرجى اختيار الجهة والممثل الصحيحين من القائمة.'
                messages.error(request, err_msg)
                failed_state = {
                    'mode': 'entity',
                    'seat_id': seat.id if seat else None,
                    'user_id': selected_user.id if selected_user else None,
                    'error': err_msg,
                }
            elif not selected_user.check_password(password):
                err_msg = f'كلمة المرور الشخصية غير صحيحة للممثل ({selected_user.full_name}).'
                messages.error(request, err_msg)
                failed_state = {
                    'mode': 'entity',
                    'seat_id': seat.id,
                    'user_id': selected_user.id,
                    'error': err_msg,
                }
            else:
                user = selected_user
                user.last_login_ip = _get_client_ip(request)
                user.save(update_fields=['last_login_ip'])
                login(request, user)

                is_proxy = (user != seat.primary_rep)
                role_label = 'أصيل' if not is_proxy else 'إنابة'
                log_action(user, 'login', request=request, notes=f'دخول عبر مقعد {seat.name} بصفة ({role_label})')

                _handle_auto_attendance_and_receipts(user, seat, request)

                messages.success(request, f'أهلاً بك {user.full_name} – ممثل {seat.name} ({role_label}).')
                if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                    return redirect(next_url)
                return redirect('/dashboard/')

        else:  # direct login (staff card or manual username/password)
            form = LoginForm(request=request, data=request.POST)
            if form.is_valid():
                user = form.get_user()
                user.last_login_ip = _get_client_ip(request)
                user.save(update_fields=['last_login_ip'])
                login(request, user)
                log_action(user, 'login', request=request, notes='تسجيل دخول مباشر')

                _handle_auto_attendance_and_receipts(user, None, request)

                messages.success(request, f'أهلاً {user.full_name}، مرحباً بك في نظام مجلس الجامعة.')
                if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                    return redirect(next_url)
                return redirect('/dashboard/')
            else:
                posted_username = request.POST.get('username', '').strip()
                staff_user_id = request.POST.get('staff_user_id', '').strip()
                err_msg = 'اسم المستخدم أو كلمة المرور غير صحيحة.'
                if staff_user_id and staff_user_id.isdigit():
                    target_u = User.objects.filter(pk=int(staff_user_id), is_active=True).first()
                    if target_u:
                        err_msg = f'كلمة المرور غير صحيحة للمستخدم ({target_u.full_name}).'
                messages.error(request, err_msg)
                failed_state = {
                    'mode': 'staff' if (staff_user_id and staff_user_id.isdigit()) else 'direct_manual',
                    'staff_user_id': int(staff_user_id) if (staff_user_id and staff_user_id.isdigit()) else None,
                    'username': posted_username,
                    'error': err_msg,
                }

    # Collect user IDs already bound to active EntitySeats
    seat_user_ids = set()
    seats_list = []
    category_counts = {
        'presidency_office': 0,
        'vice_presidents': 0,
        'deans': 0,
        'secretariat_admin': 0,
        'representatives': 0,
    }

    for s in seats:
        for uid in (s.primary_rep_id, s.deputy_rep_1_id, s.deputy_rep_2_id):
            if uid:
                seat_user_ids.add(uid)

        reps = s.get_representatives()
        for r in reps:
            r['initials'] = compute_avatar_initials(r.get('full_name', ''))

        cat_key = _get_seat_category_key(s.seat_type, s.primary_rep)
        category_counts[cat_key] = category_counts.get(cat_key, 0) + 1
        s.category_key = cat_key
        s.primary_initials = compute_avatar_initials(s.primary_rep.full_name) if s.primary_rep else 'م'

        seats_list.append({
            'id': s.id,
            'name': s.name,
            'seat_type': s.seat_type,
            'seat_type_label': s.get_seat_type_display(),
            'category_key': cat_key,
            'order': s.order,
            'reps_count': len(reps),
            'reps': reps,
        })

    # Standalone active users (e.g. Council Affairs staff, System Admin) not already on a seat
    standalone_users_qs = (
        User.objects.filter(is_active=True)
        .exclude(id__in=seat_user_ids)
        .order_by('order', 'id')
    )
    standalone_users = []
    standalone_users_list = []
    for u in standalone_users_qs:
        cat_key = _get_user_category_key(u)
        category_counts[cat_key] = category_counts.get(cat_key, 0) + 1
        u.category_key = cat_key
        u.initials = u.avatar_initials or compute_avatar_initials(u.full_name)
        u.role_badge_label = 'إدارة النظام' if u.is_super else (u.department or u.get_title_display())
        standalone_users.append(u)
        standalone_users_list.append({
            'id': u.id,
            'username': u.username,
            'full_name': u.full_name,
            'title': u.official_title or u.get_title_display(),
            'department': u.department or u.get_title_display(),
            'role_badge_label': u.role_badge_label,
            'category_key': cat_key,
            'initials': u.initials,
        })

    categories_meta = [
        {
            'key': 'presidency_office',
            'title': 'مكتب رئيس الجامعة والمستشارون والمساعدون',
            'subtitle': 'رئيس الجامعة، المستشارون، ومساعدو رئيس الجامعة',
            'count': category_counts['presidency_office'],
            'unit': 'جهات',
        },
        {
            'key': 'vice_presidents',
            'title': 'نواب رئيس الجامعة',
            'subtitle': 'الشؤون الأكاديمية، شؤون الطلاب، والدراسات العليا والبحث العلمي',
            'count': category_counts['vice_presidents'],
            'unit': 'نيابات',
        },
        {
            'key': 'deans',
            'title': 'عمداء الكليات',
            'subtitle': 'عمداء الكليات والقائمون بأعمالهم ونوابهم المعتمدون',
            'count': category_counts['deans'],
            'unit': 'كلية',
        },
        {
            'key': 'secretariat_admin',
            'title': 'الأمانة العامة وإدارة المجلس',
            'subtitle': 'الأمين العام، الإدارة العامة المساعدة لشؤون المجلس، وإدارة النظام',
            'count': category_counts['secretariat_admin'],
            'unit': 'حسابات',
        },
        {
            'key': 'representatives',
            'title': 'ممثلو النقابة وأعضاء هيئة التدريس',
            'subtitle': 'نقابة أعضاء هيئة التدريس وممثل الأساتذة المشاركين بالمجلس',
            'count': category_counts['representatives'],
            'unit': 'تمثيل',
        },
    ]

    total_cards_count = len(seats_list) + len(standalone_users_list)

    context = {
        'form': form,
        'seats': seats,
        'standalone_users': standalone_users,
        'categories_meta': categories_meta,
        'total_cards_count': total_cards_count,
        'seats_json': json.dumps(seats_list, ensure_ascii=False),
        'standalone_users_json': json.dumps(standalone_users_list, ensure_ascii=False),
        'failed_state_json': json.dumps(failed_state, ensure_ascii=False),
        'title': 'تسجيل الدخول – مجلس الجامعة',
    }
    return render(request, 'accounts/login.html', context)


def logout_view(request):
    """
    Log out the current user (POST preferred, GET accepted for simplicity).
    Redirects to /login/.
    """
    if request.user.is_authenticated:
        log_action(request.user, 'logout', request=request, notes='تسجيل خروج')
        messages.info(request, 'تم تسجيل خروجك بنجاح.')
    logout(request)
    return redirect('/login/')


# ═════════════════════════════════════════════════════════════════════════════
# Dashboard View
# ═════════════════════════════════════════════════════════════════════════════

@login_required_custom
def dashboard_view(request):
    """
    Main landing page after login.
    Shows summary statistics and quick links ONLY for permitted modules.
    Imports session/topic models lazily to avoid circular imports.
    """
    user = request.user
    stats = {
        'total_sessions': 0,
        'active_sessions': 0,
        'total_topics': 0,
        'voted_topics': 0,
        'total_users': 0,
    }
    recent_sessions = []

    if user.is_super or user.can_view_sessions:
        try:
            from council.models import CouncilSession, Topic, user_can_view_drafts
            sessions_qs = CouncilSession.objects.all()
            topics_qs = Topic.objects.all()
            if not user_can_view_drafts(user):
                sessions_qs = sessions_qs.exclude(status='draft')
                topics_qs = topics_qs.exclude(session__status='draft')
            stats['total_sessions'] = sessions_qs.count()
            stats['active_sessions'] = sessions_qs.filter(status='active').count()
            recent_sessions = list(sessions_qs.order_by('-date')[:5])
            if user.is_super or user.can_view_topics:
                stats['total_topics'] = topics_qs.count()
                stats['voted_topics'] = topics_qs.filter(status='voted').count()
        except Exception:
            pass

    if user.is_super or user.can_manage_users or user.can_grant_permissions:
        stats['total_users'] = User.objects.filter(is_active=True).count()

    context = {
        'title': 'لوحة التحكم',
        'stats': stats,
        'total_sessions': stats.get('total_sessions', 0),
        'active_sessions': stats.get('active_sessions', 0),
        'total_topics': stats.get('total_topics', 0),
        'voted_topics': stats.get('voted_topics', 0),
        'total_users': stats.get('total_users', 0),
        'recent_sessions': recent_sessions,
        'user': user,
        'has_any_permission': user.has_any_permission,
    }
    return render(request, 'accounts/dashboard.html', context)


# ═════════════════════════════════════════════════════════════════════════════
# User Management Views
# ═════════════════════════════════════════════════════════════════════════════

@login_required_custom
def user_list_view(request):
    """
    List all users with their permission summary.
    Accessible by: is_super OR can_grant_permissions OR can_manage_users.
    """
    user = request.user
    if not (user.is_super or user.can_grant_permissions or user.can_manage_users):
        messages.error(request, 'ليس لديك صلاحية لعرض قائمة المستخدمين.')
        return redirect('/dashboard/')

    users = (
        User.objects
        .select_related('council_permission')
        .order_by('order', 'id')
    )

    # Search / filter
    q = request.GET.get('q', '').strip()
    if q:
        users = users.filter(
            Q(full_name__icontains=q) |
            Q(official_title__icontains=q) |
            Q(department__icontains=q) |
            Q(username__icontains=q) |
            Q(email__icontains=q)
        )

    context = {
        'title': 'إدارة المستخدمين',
        'users': users,
        'categories': User.LOGIN_CATEGORY_CHOICES,
        'search_query': q,
    }
    return render(request, 'accounts/user_list.html', context)


@login_required_custom
def user_create_view(request):
    """
    Create a new council user manually.
    Accessible by Super Admin or users with can_manage_users / can_grant permission
    (such as the Council Affairs Data Entry person).
    """
    if not (request.user.is_super or request.user.can_manage_users or request.user.can_grant):
        messages.error(request, 'ليس لديك صلاحية لإضافة مستخدمين جدد.')
        return redirect('/dashboard/')

    form = UserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        new_user = form.save()
        # If created by department director, associate manager
        if not new_user.manager and not request.user.is_super:
            new_user.manager = request.user
            new_user.save(update_fields=['manager'])

        messages.success(
            request,
            f'تم إضافة «{new_user.full_name}» بنجاح ضمن ({new_user.get_effective_login_category_display()}) بصلاحيات صفر افتراضياً.'
        )
        if request.user.is_super or request.user.can_grant:
            return redirect('accounts:user_permissions', pk=new_user.pk)
        return redirect('accounts:user_list')

    context = {
        'title': 'إضافة مستخدم جديد',
        'form': form,
    }
    return render(request, 'accounts/user_form.html', context)


@login_required_custom
def member_import_view(request):
    """
    Bulk import council members from Excel (.xlsx, .csv) or Word (.docx).
    Accessible by Super Admin, Council Affairs director, or data entry users.
    """
    if not (request.user.is_super or request.user.can_import_members or request.user.can_manage_users or request.user.can_grant):
        messages.error(request, 'ليس لديك صلاحية لاستيراد أعضاء المجلس.')
        return redirect('/dashboard/')

    from .forms import MemberImportForm
    from .services.member_importer import parse_and_import_members

    form = MemberImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        uploaded_file = form.cleaned_data['import_file']
        default_title = form.cleaned_data['default_title']
        default_category = form.cleaned_data.get('default_category') or ''
        auto_create_seats = form.cleaned_data.get('auto_create_seats', True)

        try:
            result = parse_and_import_members(
                uploaded_file=uploaded_file,
                default_title=default_title,
                default_category=default_category,
                auto_create_seats=auto_create_seats,
                manager=request.user if not request.user.is_super else None,
            )
            created_count = result['created']
            skipped_count = result['skipped']

            if created_count > 0:
                messages.success(
                    request,
                    f'تم استيراد وإنشاء حسابات لـ {created_count} عضواً بنجاح وبصلاحيات صفر بانتظار التخويل.'
                )
            if skipped_count > 0:
                messages.warning(
                    request,
                    f'تم تخطي {skipped_count} سطراً بسبب عدم اكتمال البيانات أو التكرار.'
                )
            return redirect('accounts:user_list')
        except Exception as exc:
            messages.error(request, f'حدث خطأ أثناء معالجة الملف: {str(exc)}')

    context = {
        'title': 'استيراد أعضاء المجلس من ملف',
        'form': form,
    }
    return render(request, 'accounts/member_import.html', context)


@login_required_custom
def download_member_template_view(request):
    """
    Download sample Excel template (.xlsx) for bulk importing council members.
    """
    if not (request.user.is_super or request.user.can_import_members or request.user.can_manage_users or request.user.can_grant):
        messages.error(request, 'ليس لديك صلاحية لتحميل نموذج الاستيراد.')
        return redirect('/dashboard/')

    from django.http import HttpResponse
    from .services.member_importer import generate_sample_excel_template

    excel_io = generate_sample_excel_template()
    response = HttpResponse(
        excel_io.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = "attachment; filename*=UTF-8''%D9%86%D9%85%D9%88%D8%B0%D8%AC_%D8%A7%D8%B3%D8%AA%D9%8A%D8%B1%D8%A7%D8%AF_%D8%A3%D8%B9%D8%B6%D8%A7%D8%A1_%D8%A7%D9%84%D9%85%D8%AC%D9%84%D8%B3.xlsx"
    return response


@login_required_custom
def user_edit_view(request, pk):
    """
    Edit an existing user's profile (name, title, email, active status).
    Accessible by: is_super OR can_manage_users OR can_grant.
    """
    current_user = request.user
    if not (current_user.is_super or current_user.can_manage_users or current_user.can_grant):
        messages.error(request, 'ليس لديك صلاحية لتعديل بيانات المستخدمين.')
        return redirect('/dashboard/')

    target_user = get_object_or_404(User, pk=pk)

    if not current_user.is_super and target_user.is_super:
        messages.error(request, 'لا يمكنك تعديل بيانات المسؤول الأعلى.')
        return redirect('accounts:user_list')

    form = UserEditForm(request.POST or None, instance=target_user)
    if request.method == 'POST' and form.is_valid():
        updated = form.save()
        updated.avatar_initials = ''
        updated.save()
        messages.success(request, f'تم تحديث بيانات «{updated.full_name}» بنجاح.')
        return redirect('accounts:user_list')

    context = {
        'title': f'تعديل بيانات: {target_user.full_name}',
        'form': form,
        'target_user': target_user,
    }
    return render(request, 'accounts/user_edit.html', context)


@login_required_custom
def user_permissions_view(request, pk):
    """
    Smart Permission Matrix:
    Create or update a user's CouncilPermission record.
    Supports Master Select All, granular checkboxes, and role presets.
    Accessible by Super Admin or Director with can_grant permission.
    """
    current_user = request.user
    if not (current_user.is_super or current_user.can_grant):
        messages.error(request, 'ليس لديك صلاحية لتخويل الصلاحيات.')
        return redirect('/dashboard/')

    target_user = get_object_or_404(User, pk=pk)

    if target_user.is_super:
        messages.info(
            request,
            f'المستخدم «{target_user.full_name}» هو مسؤول أعلى ولديه كافة صلاحيات النظام تلقائياً.'
        )
        return redirect('accounts:user_list')

    # Authority hierarchy guard: non-super cannot manage someone outside their team
    if not current_user.is_super and target_user.manager and target_user.manager != current_user:
        messages.error(request, 'ليس لديك صلاحية لتخويل مستخدم لا يتبع إدارتك مباشرة.')
        return redirect('accounts:user_list')

    permission_obj, created = CouncilPermission.objects.get_or_create(
        user=target_user,
        defaults={'granted_by': current_user},
    )

    form = PermissionForm(request.POST or None, instance=permission_obj)
    if request.method == 'POST' and form.is_valid():
        perm = form.save(commit=False)
        perm.user = target_user
        perm.granted_by = current_user
        perm.save()
        log_action(
            current_user, 'permission', obj=perm, request=request,
            notes=f'تحديث صلاحيات {target_user.full_name} (الممنوح: {perm.count_granted()} صلاحية)'
        )
        messages.success(
            request,
            f'تم تحديث واعتماد صلاحيات «{target_user.full_name}» بنجاح (الممنوح: {perm.count_granted()} صلاحية).'
        )
        return redirect('accounts:user_list')

    context = {
        'title': f'لوحة الصلاحيات الذكية: {target_user.full_name}',
        'form': form,
        'target_user': target_user,
        'permission_obj': permission_obj,
        'is_new': created,
        'permission_groups': PermissionForm.PERMISSION_GROUPS,
    }
    return render(request, 'accounts/user_permissions.html', context)


@login_required_custom
def user_delete_view(request, pk):
    """
    Delete or deactivate a user account.
    Accessible by Super Admin or Director for their subordinate staff.
    Supports permanent database deletion or soft deactivation.
    """
    current_user = request.user
    target_user = get_object_or_404(User, pk=pk)

    # Authority check
    can_manage = current_user.is_super or (
        (current_user.can_manage_users or current_user.can_grant) and (target_user.manager == current_user or current_user.can_manage_users)
    )
    if not can_manage:
        messages.error(request, 'ليس لديك صلاحية لحذف هذا المستخدم.')
        return redirect('accounts:user_list')

    if target_user == current_user:
        messages.error(request, 'لا يمكنك حذف حسابك الخاص.')
        return redirect('accounts:user_list')

    if target_user.is_super and not current_user.is_super:
        messages.error(request, 'لا يمكن حذف حساب المسؤول الأعلى.')
        return redirect('accounts:user_list')

    if request.method == 'POST':
        action_type = request.POST.get('action_type', 'permanent_delete')
        user_name = target_user.full_name

        if action_type == 'deactivate':
            target_user.is_active = False
            target_user.save(update_fields=['is_active'])
            messages.warning(
                request,
                f'تم تعطيل حساب «{user_name}» بنجاح. يمكنك إعادة تفعيله لاحقاً.'
            )
        else:
            # Permanent deletion from DB
            target_user.delete()
            messages.success(
                request,
                f'تم حذف المستخدم «{user_name}» نهائياً من النظام بنجاح.'
            )
        return redirect('accounts:user_list')

    context = {
        'title': f'حذف المستخدم: {target_user.full_name}',
        'target_user': target_user,
    }
    return render(request, 'accounts/user_confirm_delete.html', context)


@login_required_custom
def user_activate_view(request, pk):
    """
    Re-activate a previously deactivated user. Only Super Admin.
    POST only.
    """
    if not request.user.is_super:
        messages.error(request, 'إعادة تفعيل المستخدمين مخصصة للمسؤول الأعلى فقط.')
        return redirect('/dashboard/')

    target_user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        target_user.is_active = True
        target_user.save(update_fields=['is_active'])
        messages.success(request, f'تم إعادة تفعيل حساب «{target_user.full_name}» بنجاح.')
    return redirect('accounts:user_list')


# ═════════════════════════════════════════════════════════════════════════════
# Profile & Password Views
# ═════════════════════════════════════════════════════════════════════════════

@login_required_custom
def profile_view(request):
    """
    Display the currently logged-in user's profile page.
    Shows personal info, permission summary, and activity info.
    """
    user = request.user
    permission = user.get_permission()

    context = {
        'title': 'ملفي الشخصي',
        'profile_user': user,
        'permission': permission,
    }
    return render(request, 'accounts/profile.html', context)


@login_required_custom
def change_password_view(request):
    """
    Allow authenticated user to change their own password ONLY if granted can_change_password.
    Updates session auth hash so the user stays logged in after the change.
    """
    if not (request.user.is_super or request.user.can_change_password):
        messages.error(request, 'ليس لديك صلاحية لتغيير كلمة المرور.')
        return redirect('/dashboard/')

    form = ChangePasswordForm(user=request.user, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        updated_user = form.save()
        # Keep the session alive with the new password hash
        update_session_auth_hash(request, updated_user)
        messages.success(request, 'تم تغيير كلمة المرور بنجاح.')
        return redirect('accounts:profile')

    context = {
        'title': 'تغيير كلمة المرور',
        'form': form,
    }
    return render(request, 'accounts/change_password.html', context)


# ═════════════════════════════════════════════════════════════════════════════
# م5 – إدارة الممثلين بالإنابة (Seat Deputies Management)
# ═════════════════════════════════════════════════════════════════════════════

@login_required_custom
def seat_deputies_view(request):
    """
    Allow a representative or manager to view and manage the deputies for their
    entity seat (deputy_rep_1, deputy_rep_2) ONLY when granted can_manage_delegates.
    """
    from council.models import EntitySeat
    user = request.user

    if not (user.is_super or user.can_manage_delegates):
        messages.error(request, 'ليس لديك صلاحية لإدارة الممثلين بالإنابة.')
        return redirect('/dashboard/')

    # Superusers or users with can_manage_users can manage any seat
    if user.is_super or getattr(user, 'can_manage_users', False):
        user_seats = EntitySeat.objects.filter(is_active=True).order_by('order', 'name')
    else:
        user_seats = EntitySeat.objects.filter(primary_rep=user, is_active=True).order_by('order', 'name')

    if not user_seats.exists():
        messages.error(request, 'أنت لست ممثلاً أولاً لأي مقعد في مجلس الجامعة.')
        return redirect('/dashboard/')

    selected_seat_id = request.GET.get('seat_id') or request.POST.get('seat_id')
    seat = None
    if selected_seat_id:
        seat = user_seats.filter(pk=selected_seat_id).first()
    if not seat:
        seat = user_seats.first()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_deputies':
            deputy1_id = request.POST.get('deputy_rep_1')
            deputy2_id = request.POST.get('deputy_rep_2')

            d1 = User.objects.filter(pk=deputy1_id, is_active=True).first() if deputy1_id else None
            d2 = User.objects.filter(pk=deputy2_id, is_active=True).first() if deputy2_id else None

            seat.deputy_rep_1 = d1
            seat.deputy_rep_2 = d2
            seat.save(update_fields=['deputy_rep_1', 'deputy_rep_2', 'updated_at'])

            log_action(user, 'update', obj=seat, request=request,
                       notes=f'تحديث الممثلين بالإنابة لمقعد {seat.name}')
            messages.success(request, f'تم حفظ الممثلين بالإنابة لمقعد ({seat.name}) بنجاح.')
            return redirect(f'/seats/deputies/?seat_id={seat.id}')

        elif action == 'create_deputy':
            full_name = request.POST.get('full_name', '').strip()
            username  = request.POST.get('username', '').strip()
            password  = request.POST.get('password', '').strip() or '123456'
            title     = request.POST.get('title', 'vice_dean_academic')
            official_title = request.POST.get('official_title', '').strip()
            slot      = request.POST.get('slot', '1')

            if not full_name or not username or not password:
                messages.error(request, 'يرجى ملء جميع الحقول المطلوبة لإنشاء حساب النائب.')
            elif User.objects.filter(username=username).exists():
                messages.error(request, f'اسم المستخدم ({username}) مستخدم مسبقاً، يرجى اختيار اسم آخر.')
            else:
                new_user = User.objects.create_user(
                    username=username,
                    password=password,
                    full_name=full_name,
                    title=title,
                    official_title=official_title or f'نائب عميد {seat.name}',
                    department=seat.name,
                    order=seat.order,
                    is_active=True,
                )
                if slot == '1':
                    seat.deputy_rep_1 = new_user
                else:
                    seat.deputy_rep_2 = new_user
                seat.save(update_fields=['deputy_rep_1', 'deputy_rep_2', 'updated_at'])

                log_action(user, 'create', obj=new_user, request=request,
                           notes=f'إنشاء وتعيين نائب لمقعد {seat.name}: {new_user.full_name}')
                messages.success(request, f'تم إنشاء وتعيين النائب ({new_user.full_name}) لمقعد ({seat.name}) بنجاح.')
                return redirect(f'/seats/deputies/?seat_id={seat.id}')

    eligible_users = User.objects.filter(is_active=True).exclude(pk=seat.primary_rep_id).order_by('full_name')

    context = {
        'user_seats': user_seats,
        'seat': seat,
        'eligible_users': eligible_users,
        'title': f'إدارة الممثلين بالإنابة – {seat.name}',
    }
    return render(request, 'accounts/seat_deputies.html', context)
