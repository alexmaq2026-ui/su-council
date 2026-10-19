# -*- coding: utf-8 -*-
"""
Strict Isolation & Air-Gap Controller
University Council Management System
====================================
Manages the strict isolation state between the local server and external servers (Supabase / Render).
Auto-detects the running environment:
1. Local Server (Windows / On-Premise):
   - Strict Air-Gap Isolation active by default.
   - Enforces local SQLite and local storage.
   - Live session polling runs at 0ms latency with zero external dependency.
   - Controlled via the Admin toggle button.
2. External Cloud Server (Render / Cloud Container):
   - Automatically detects cloud deployment environment.
   - Runs in independent cloud mode connected to Supabase.
   - Zero conflicts, zero code deletion, seamless deployments.
"""
import os
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger('isolation_guard')

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / 'isolation_config.json'

def is_running_on_external_server() -> bool:
    """
    Detect if the code is currently running on Render or external cloud hosting.
    Render automatically provides RENDER=true, RENDER_SERVICE_ID, etc.
    """
    return bool(
        os.getenv('RENDER') == 'true'
        or os.getenv('IS_EXTERNAL_SERVER') == 'true'
        or os.getenv('RENDER_SERVICE_ID')
        or '/opt/render' in str(BASE_DIR)
    )

DEFAULT_LOCAL_CONFIG = {
    "is_isolated": True,
    "is_external_server": False,
    "mode": "ISOLATED",   # "ISOLATED" or "CONNECTED"
    "strict_guard_active": True,
    "allow_external_sync": False,
    "last_toggled": datetime.now().isoformat(),
    "toggled_by": "مدير النظام",
    "status_title": "وضع العزل الصارم (محلي 100%)",
    "status_description": "السيرفر المحلي معزول تماماً عن السيرفر الخارجي. قاعدة البيانات والملفات ونبضات الجلسة تعمل محلياً بأقصى سرعة واستجابة فورية دون أي اتصال خارجي."
}

CLOUD_SERVER_CONFIG = {
    "is_isolated": False,
    "is_external_server": True,
    "mode": "CLOUD_PRODUCTION",
    "strict_guard_active": False,
    "allow_external_sync": True,
    "last_toggled": "تلقائي (سحابي)",
    "toggled_by": "سيرفر النشر السحابي (Render)",
    "status_title": "السيرفر السحابي المستقل (Render Cloud)",
    "status_description": "يعمل النظام في البيئة السحابية المستقلة (Render) متصلاً بقاعدة بيانات Supabase المخصصة للنشر الخارجي."
}

def get_isolation_status() -> dict:
    """Retrieve the current isolation status depending on the environment."""
    if is_running_on_external_server():
        return CLOUD_SERVER_CONFIG.copy()

    if not CONFIG_FILE.exists():
        save_isolation_status(DEFAULT_LOCAL_CONFIG)
        return DEFAULT_LOCAL_CONFIG.copy()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            data["is_external_server"] = False
            for k, v in DEFAULT_LOCAL_CONFIG.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception as e:
        logger.error(f"Error reading isolation config: {e}")
        return DEFAULT_LOCAL_CONFIG.copy()

def save_isolation_status(config: dict) -> bool:
    """Save isolation status to local config file atomically."""
    if is_running_on_external_server():
        return True  # Read-only in cloud environment
    try:
        temp_file = BASE_DIR / 'isolation_config.tmp'
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        if temp_file.exists():
            if CONFIG_FILE.exists():
                CONFIG_FILE.unlink()
            temp_file.rename(CONFIG_FILE)
        return True
    except Exception as e:
        logger.error(f"Error saving isolation config: {e}")
        return False

def is_isolated() -> bool:
    """
    Check if the system is currently in strict isolated mode.
    Always returns False on Render (cloud server).
    Returns the admin's chosen state on local machines.
    """
    if is_running_on_external_server():
        return False
    status = get_isolation_status()
    return bool(status.get("is_isolated", True))

def set_isolation_mode(mode: str, toggled_by: str = "مدير النظام") -> dict:
    """
    Toggle between 'ISOLATED' and 'CONNECTED' on local server.
    Returns the updated status dictionary.
    """
    if is_running_on_external_server():
        return CLOUD_SERVER_CONFIG.copy()

    mode = mode.upper().strip()
    is_iso = (mode == "ISOLATED")
    
    status = {
        "is_isolated": is_iso,
        "is_external_server": False,
        "mode": "ISOLATED" if is_iso else "CONNECTED",
        "strict_guard_active": is_iso,
        "allow_external_sync": not is_iso,
        "last_toggled": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "toggled_by": toggled_by,
        "status_title": "وضع العزل الصارم (محلي 100%)" if is_iso else "وضع الربط السحابي (مفعل)",
        "status_description": (
            "السيرفر المحلي معزول تماماً عن السيرفر الخارجي. قاعدة البيانات والملفات ونبضات الجلسة تعمل محلياً بأقصى سرعة واستجابة فورية دون أي اتصال خارجي."
            if is_iso else
            "تم فتح قناة الاتصال بالسيرفر الخارجي. يمكنك الآن إجراء مزامنة بيانات يدوية أو التبديل للوضع السحابي عند الحاجة."
        )
    }
    save_isolation_status(status)
    logger.info(f"Isolation mode changed to {status['mode']} by {toggled_by}")
    return status
