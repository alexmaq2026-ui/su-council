"""
Custom Storage Backend for Supabase Object Storage
Allows seamless file uploads to Supabase Storage with local fallback and mirroring.
"""
import os
import posixpath
import re
import hashlib
import mimetypes
import logging
import requests
from django.conf import settings
from django.core.files.storage import Storage
from django.core.files.base import ContentFile, File
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


@deconstructible
class SupabaseMediaStorage(Storage):
    """
    Custom Django Storage backend that uploads media files to Supabase Storage.
    Maintains a local copy in MEDIA_ROOT for caching and quick local access,
    and returns public URLs pointing directly to Supabase Storage CDN.
    """

    def __init__(self, bucket_name='council-media', supabase_url=None, supabase_key=None, **kwargs):
        self.bucket_name = getattr(settings, 'SUPABASE_STORAGE_BUCKET', bucket_name)
        self.supabase_url = (supabase_url or os.getenv('SUPABASE_URL', '')).rstrip('/')
        self.supabase_key = supabase_key or os.getenv('SUPABASE_KEY', '')
        self.local_media_root = getattr(settings, 'MEDIA_ROOT', None)

    def _sanitize_key(self, name):
        """
        Ensure storage key contains only ASCII alphanumeric characters, hyphens, and underscores,
        preventing 'InvalidKey' errors in S3 / Supabase object storage.
        """
        clean = name.replace('\\', '/')
        dir_part, filename = posixpath.split(clean)
        stem, ext = posixpath.splitext(filename)
        stem = stem.rstrip('.')
        
        safe_stem = re.sub(r'[^a-zA-Z0-9\-]', '_', stem)
        safe_stem = re.sub(r'_+', '_', safe_stem).strip('_')
        
        if len(safe_stem) < 3:
            stem_hash = hashlib.md5(stem.encode('utf-8', errors='ignore')).hexdigest()[:10]
            safe_filename = f"att_{stem_hash}{ext.lower()}"
        else:
            safe_filename = f"{safe_stem[:60]}{ext.lower()}"
            
        return f"{dir_part}/{safe_filename}" if dir_part else safe_filename

    def _save(self, name, content):
        safe_name = self._sanitize_key(name)
        
        # Read content data
        if hasattr(content, 'chunks'):
            data = b''.join(chunk for chunk in content.chunks())
        elif hasattr(content, 'read'):
            content.seek(0)
            data = content.read()
        else:
            data = bytes(content)

        # 1. Upload to Supabase Storage (Only if NOT in isolated mode)
        from config.isolation import is_isolated
        if not is_isolated() and self.supabase_url and self.supabase_key:
            content_type = mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'

            upload_url = f"{self.supabase_url}/storage/v1/object/{self.bucket_name}/{safe_name}"
            headers = {
                "apikey": self.supabase_key,
                "Authorization": f"Bearer {self.supabase_key}",
                "x-upsert": "true",
                "Content-Type": content_type,
            }
            try:
                resp = requests.post(upload_url, headers=headers, data=data, timeout=45)
                if resp.status_code not in (200, 201):
                    logger.warning("Supabase storage upload returned status %s: %s", resp.status_code, resp.text)
            except Exception as e:
                logger.error("Failed to upload file to Supabase storage: %s", e)

        # 2. Local mirror for caching/offline access if MEDIA_ROOT exists
        if self.local_media_root:
            try:
                local_path = os.path.join(self.local_media_root, safe_name.replace('/', os.sep))
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, 'wb') as f:
                    f.write(data)
            except Exception as e:
                logger.warning("Failed to mirror file locally: %s", e)

        return safe_name

    def url(self, name):
        if not name:
            return ''
        clean_name = name.replace('\\', '/')
        if clean_name.startswith('http://') or clean_name.startswith('https://'):
            return clean_name
            
        from config.isolation import is_isolated
        if not is_isolated() and self.supabase_url:
            return f"{self.supabase_url}/storage/v1/object/public/{self.bucket_name}/{clean_name}"
            
        media_url = getattr(settings, 'MEDIA_URL', '/media/')
        return f"{media_url.rstrip('/')}/{clean_name}"

    def exists(self, name):
        if not name:
            return False
        clean_name = self._sanitize_key(name)
        if self.local_media_root:
            local_path = os.path.join(self.local_media_root, clean_name.replace('/', os.sep))
            if os.path.exists(local_path):
                return True
        from config.isolation import is_isolated
        if not is_isolated() and self.supabase_url:
            try:
                resp = requests.head(self.url(clean_name), timeout=10)
                return resp.status_code == 200
            except Exception:
                pass
        return False

    def delete(self, name):
        if not name:
            return
        clean_name = self._sanitize_key(name)
        # Delete local copy
        if self.local_media_root:
            local_path = os.path.join(self.local_media_root, clean_name.replace('/', os.sep))
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass
        # Delete from Supabase Storage
        from config.isolation import is_isolated
        if not is_isolated() and self.supabase_url and self.supabase_key:
            del_url = f"{self.supabase_url}/storage/v1/object/{self.bucket_name}"
            headers = {
                "apikey": self.supabase_key,
                "Authorization": f"Bearer {self.supabase_key}",
                "Content-Type": "application/json",
            }
            try:
                requests.delete(del_url, headers=headers, json={"prefixes": [clean_name]}, timeout=15)
            except Exception as e:
                logger.warning("Supabase storage delete failed for %s: %s", clean_name, e)

    def _open(self, name, mode='rb'):
        clean_name = self._sanitize_key(name)
        if self.local_media_root:
            local_path = os.path.join(self.local_media_root, clean_name.replace('/', os.sep))
            if os.path.exists(local_path):
                return File(open(local_path, mode))
        from config.isolation import is_isolated
        if not is_isolated() and self.supabase_url:
            resp = requests.get(self.url(clean_name), timeout=30)
            if resp.status_code == 200:
                return ContentFile(resp.content, name=clean_name)
        raise FileNotFoundError(f"File not found in storage: {name}")


    def path(self, name):
        clean_name = self._sanitize_key(name)
        if self.local_media_root:
            return os.path.join(self.local_media_root, clean_name.replace('/', os.sep))
        raise NotImplementedError("Supabase storage does not have a local absolute file path.")

    def size(self, name):
        clean_name = self._sanitize_key(name)
        if self.local_media_root:
            local_path = os.path.join(self.local_media_root, clean_name.replace('/', os.sep))
            if os.path.exists(local_path):
                return os.path.getsize(local_path)
        if self.supabase_url:
            try:
                resp = requests.head(self.url(clean_name), timeout=10)
                if resp.status_code == 200 and 'content-length' in resp.headers:
                    return int(resp.headers['content-length'])
            except Exception:
                pass
        return 0
