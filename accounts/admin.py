"""
Accounts Admin - University Council Management System
Registers custom User and CouncilPermission with the Django admin site.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import CouncilPermission, User


class CouncilPermissionInline(admin.StackedInline):
    model = CouncilPermission
    can_delete = False
    verbose_name = 'صلاحيات المجلس'
    verbose_name_plural = 'صلاحيات المجلس'
    fk_name = 'user'
    extra = 0
    readonly_fields = ('granted_at',)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [CouncilPermissionInline]
    list_display  = (
        'username', 'full_name', 'title_badge',
        'department', 'email', 'is_super_badge', 'is_active_badge', 'date_joined',
    )
    list_filter   = ('is_super', 'is_active', 'title', 'date_joined')
    search_fields = ('username', 'full_name', 'email', 'department')
    ordering      = ('full_name',)
    readonly_fields = ('date_joined', 'last_login', 'last_login_ip', 'avatar_initials')

    fieldsets = (
        ('معلومات الدخول', {
            'fields': ('username', 'password'),
        }),
        ('البيانات الشخصية والإدارية', {
            'fields': ('full_name', 'title', 'department', 'phone', 'email', 'avatar_initials', 'manager'),
        }),
        ('الصلاحيات الأساسية', {
            'fields': ('is_active', 'is_super', 'is_staff', 'is_superuser'),
        }),
        ('سجل النشاط', {
            'fields': ('date_joined', 'last_login', 'last_login_ip'),
            'classes': ('collapse',),
        }),
    )

    add_fieldsets = (
        ('إنشاء مستخدم جديد', {
            'classes': ('wide',),
            'fields': (
                'username', 'full_name', 'title', 'department', 'phone', 'email',
                'password1', 'password2',
                'is_active', 'is_super', 'manager',
            ),
        }),
    )

    @admin.display(description='اللقب الوظيفي', ordering='title')
    def title_badge(self, obj):
        return obj.get_title_display()

    @admin.display(description='سوبر أدمن', boolean=True, ordering='is_super')
    def is_super_badge(self, obj):
        return obj.is_super

    @admin.display(description='نشط', boolean=True, ordering='is_active')
    def is_active_badge(self, obj):
        return obj.is_active


@admin.register(CouncilPermission)
class CouncilPermissionAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'can_vote', 'enforce_force_majeure', 'can_draft_decision', 'can_add_topic',
        'can_upload_attachments', 'can_manage_attendance', 'can_grant_permissions',
        'granted_by', 'granted_at',
    )
    list_filter  = (
        'can_vote', 'enforce_force_majeure', 'can_draft_decision', 'can_add_topic',
        'can_start_session_live', 'can_reopen_topic_live', 'can_moderate_live_session',
        'can_manage_attendance', 'can_grant_permissions',
    )
    search_fields = ('user__full_name', 'user__username', 'granted_by__full_name')
    readonly_fields = ('granted_at',)
    raw_id_fields = ('user', 'granted_by')
