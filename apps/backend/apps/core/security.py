from __future__ import annotations

import imghdr
from functools import wraps
from io import BytesIO
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.crypto import constant_time_compare
from PIL import Image, UnidentifiedImageError


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def rate_limit(scope: str, limit: int, window: int, *, key_by: str = 'ip', methods: tuple[str, ...] = ('POST',), limit_setting: str | None = None):
    """Small dependency-free fixed-window limiter.

    It is safe for one-process/local deployments. For multi-worker/multi-node SaaS,
    configure a shared Django cache backend such as Redis so the limit is global.
    By default only POST-like mutations are counted; public GET pages stay cacheable.
    """
    allowed_methods = {method.upper() for method in methods}

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if getattr(settings, 'RATELIMIT_ENABLED', True) is False or request.method.upper() not in allowed_methods:
                return view_func(request, *args, **kwargs)
            if key_by == 'user' and request.user.is_authenticated:
                identity = f'user:{request.user.pk}'
            else:
                identity = f'ip:{client_ip(request)}'
            current_limit = int(getattr(settings, limit_setting, limit)) if limit_setting else limit
            cache_key = f'rl:{scope}:{identity}'
            added = cache.add(cache_key, 1, timeout=window)
            count = 1 if added else cache.incr(cache_key)
            if count > current_limit:
                retry_after = cache.ttl(cache_key) if hasattr(cache, 'ttl') else window
                if request.headers.get('accept', '').startswith('application/json') or request.path.startswith('/api/'):
                    response = JsonResponse({'ok': False, 'error': 'rate_limited'}, status=429)
                else:
                    response = render(request, 'public/rate_limited.html', status=429)
                response['Retry-After'] = str(max(1, retry_after if isinstance(retry_after, int) else window))
                return response
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


ALLOWED_IMAGE_FORMATS = {'PNG', 'JPEG', 'WEBP'}
ALLOWED_IMAGE_MIME_PREFIX = {'png': 'image/png', 'jpeg': 'image/jpeg', 'webp': 'image/webp'}


def allowed_qr_redirect_hosts():
    hosts = set(getattr(settings, 'QR_REDIRECT_ALLOWED_HOSTS', []))
    app_host = urlparse(getattr(settings, 'APP_BASE_URL', '')).netloc
    if app_host:
        hosts.add(app_host)
    hosts.update(host for host in getattr(settings, 'ALLOWED_HOSTS', []) if host not in {'*', ''})
    return {host.lower() for host in hosts}


def validate_qr_redirect_url(value):
    value = (value or '').strip()
    if not value:
        return ''
    lowered = value.lower()
    if lowered.startswith(('javascript:', 'data:', 'file:')):
        raise ValidationError('Schéma de redirection interdit.')
    if value.startswith('/'):
        if value.startswith('//') or value.startswith('/\\'):
            raise ValidationError('URL relative invalide.')
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValidationError('Utilisez une URL relative ou une URL http(s) autorisée.')
    if parsed.netloc.lower() not in allowed_qr_redirect_hosts():
        raise ValidationError('Domaine de redirection non autorisé.')
    return value


def validate_uploaded_image(uploaded_file, *, max_size_mb: int, max_width: int, max_height: int, label: str = 'Image'):
    if not uploaded_file:
        return uploaded_file
    if getattr(uploaded_file, 'size', 0) > max_size_mb * 1024 * 1024:
        raise ValidationError(f'{label} trop lourde : maximum {max_size_mb} Mo.')

    pos = uploaded_file.tell() if hasattr(uploaded_file, 'tell') else None
    raw = uploaded_file.read()
    if hasattr(uploaded_file, 'seek'):
        uploaded_file.seek(pos or 0)
    detected = imghdr.what(None, raw)
    if detected == 'jpg':
        detected = 'jpeg'
    if detected not in ALLOWED_IMAGE_MIME_PREFIX:
        raise ValidationError(f'{label} invalide : utilisez PNG, JPG ou WebP.')

    try:
        with Image.open(BytesIO(raw)) as img:
            img.verify()
        with Image.open(BytesIO(raw)) as img:
            width, height = img.size
            if img.format not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError(f'{label} invalide : format non autorisé.')
            if width > max_width or height > max_height:
                raise ValidationError(f'{label} trop grande : maximum {max_width}×{max_height}px.')
    except (UnidentifiedImageError, OSError):
        raise ValidationError(f'{label} invalide : fichier image illisible.')

    return uploaded_file
