# -*- coding: utf-8 -*-
"""
Isolation & Air-Gap Views & APIs
University Council Management System
====================================
Provides Super Admins with real-time controls to strictly isolate the local server
from external servers or authorize controlled manual synchronization.
"""
import os
import json
import logging
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_protect

from config.isolation import get_isolation_status, set_isolation_mode, is_isolated
from council.models import AuditLog
from council.audit import log_action


logger = logging.getLogger('isolation')


def check_admin_permission(user):
    """Only Super Admins can toggle isolation and cloud synchronization."""
    return bool(user and user.is_authenticated and getattr(user, 'is_super', False))


@login_required(login_url='/login/')
@require_GET
def api_isolation_status(request):
    """Get the current isolation mode status."""
    if not check_admin_permission(request.user):
        return JsonResponse({'ok': False, 'error': 'غير مصرّح لك بالوصول.'}, status=403)
    
    status = get_isolation_status()
    return JsonResponse({
        'ok': True,
        'status': status
    })


@login_required(login_url='/login/')
@require_POST
def api_toggle_isolation(request):
    """
    Toggle between 'ISOLATED' and 'CONNECTED' modes.
    Strictly restricted to Super Admins.
    """
    user = request.user
    if not check_admin_permission(user):
        return JsonResponse({'ok': False, 'error': 'تعديل وضع العزل مقتصر على مدير النظام الأعلى فقط.'}, status=403)

    current_status = get_isolation_status()
    current_mode = current_status.get('mode', 'ISOLATED')
    new_mode = 'CONNECTED' if current_mode == 'ISOLATED' else 'ISOLATED'

    try:
        updated_status = set_isolation_mode(new_mode, toggled_by=user.full_name or user.username)
        
        # Log to AuditLog
        action_name = "تفعيل وضع العزل الصارم المحلي" if new_mode == "ISOLATED" else "تفعيل وضع الربط والمزامنة السحابية"
        details = (
            f"قام مدير النظام ({user.full_name}) بتحويل وضع النظام إلى: {updated_status['status_title']}. "
            f"الحالة: {updated_status['status_description']}"
        )
        log_action(
            user=user,
            action='update',
            request=request,
            object_repr="منظومة العزل الصارم",
            notes=f"[{action_name}] {details}"
        )


        return JsonResponse({
            'ok': True,
            'mode': updated_status['mode'],
            'is_isolated': updated_status['is_isolated'],
            'status_title': updated_status['status_title'],
            'status_description': updated_status['status_description'],
            'last_toggled': updated_status['last_toggled'],
            'toggled_by': updated_status['toggled_by'],
            'message': f"تم بنجاح {action_name}."
        })

    except Exception as e:
        logger.error(f"Failed to toggle isolation mode: {e}")
        return JsonResponse({'ok': False, 'error': f'تعذر تعديل وضع العزل: {str(e)}'}, status=500)


@login_required(login_url='/login/')
@require_POST
def api_manual_sync_cloud(request):
    """
    Controlled Manual Synchronization with External Server (Supabase).
    Strictly blocked if isolation mode is active.
    """
    user = request.user
    if not check_admin_permission(user):
        return JsonResponse({'ok': False, 'error': 'إجراء المزامنة مقتصر على مدير النظام الأعلى فقط.'}, status=403)

    if is_isolated():
        return JsonResponse({
            'ok': False,
            'error': 'المزامنة محظورة تماماً أثناء تفعيل وضع العزل الصارم. يرجى تفعيل وضع الربط أولاً ثم إعادة المحاولة.'
        }, status=400)

    try:
        # Determine sync direction: 'push' (local -> cloud) or 'pull' (cloud -> local)
        try:
            body = json.loads(request.body) if request.body else {}
        except Exception:
            body = {}
        direction = body.get('direction', 'push')

        database_url = getattr(settings, 'DATABASE_URL', None) or os.getenv('DATABASE_URL')
        if not database_url:
            return JsonResponse({'ok': False, 'error': 'لم يتم العثور على رابط قاعدة البيانات السحابية (DATABASE_URL).'}, status=400)

        import subprocess
        script_name = "fast_migrate.py" if direction == "push" else "sync_down.py"
        script_path = settings.BASE_DIR / script_name

        if not script_path.exists():
            return JsonResponse({'ok': False, 'error': f'ملف المزامنة ({script_name}) غير موجود.'}, status=404)

        result = subprocess.run(
            ['python', str(script_path)],
            cwd=str(settings.BASE_DIR),
            capture_output=True,
            text=True,
            timeout=180
        )

        success = (result.returncode == 0)
        output_snippet = (result.stdout or '')[-500:]

        # Log to AuditLog
        action_name = f"مزامنة بيانات يدوية ({direction.upper()})"
        log_action(
            user=user,
            action='update',
            request=request,
            object_repr="مزامنة سحابية يدوية",
            notes=f"[{action_name}] تم تنفيذ المزامنة بنجاح: {success}. تفاصيل: {output_snippet}"
        )



        return JsonResponse({
            'ok': success,
            'message': 'اكتملت المزامنة بنجاح.' if success else 'حدث خطأ أثناء تنفيذ المزامنة.',
            'output': output_snippet,
            'error': result.stderr if not success else None
        })

    except subprocess.TimeoutExpired:
        return JsonResponse({'ok': False, 'error': 'استغرقت عملية المزامنة وقتاً أطول من المتوقع (انتهت المهلة).'}, status=504)
    except Exception as e:
        logger.error(f"Manual sync error: {e}")
        return JsonResponse({'ok': False, 'error': f'خطأ أثناء المزامنة: {str(e)}'}, status=500)
