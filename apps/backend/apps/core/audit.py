import logging

from apps.core.models import AuditLog

logger = logging.getLogger(__name__)

SENSITIVE_METADATA_KEYS = {'password', 'secret', 'token', 'totp', 'totp_code', 'csrfmiddlewaretoken'}


def _client_ip(request):
    forwarded_for = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded_for or request.META.get('REMOTE_ADDR') or None


def _safe_metadata(metadata):
    if not metadata:
        return {}
    safe = {}
    for key, value in dict(metadata).items():
        key_str = str(key)
        if key_str.lower() in SENSITIVE_METADATA_KEYS:
            continue
        safe[key_str] = value
    return safe


def _target_identity(target):
    if target is None:
        return '', ''
    target_type = target.__class__.__name__
    target_id = getattr(target, 'pk', None) or getattr(target, 'id', None) or ''
    return target_type, str(target_id) if target_id is not None else ''


def log_audit_event(request, action, target=None, merchant=None, metadata=None):
    """Best-effort business audit log.

    Never raise to callers: sensitive actions must not fail because logging did.
    Keep metadata intentionally small and scrub obvious secret fields.
    """
    try:
        actor = getattr(request, 'user', None)
        if not getattr(actor, 'is_authenticated', False):
            actor = None
        if merchant is None and target is not None:
            merchant = getattr(target, 'merchant', None)
            if merchant is None and getattr(target, 'customer', None) is not None:
                merchant = getattr(target.customer, 'merchant', None)
            if merchant is None and getattr(target, 'campaign', None) is not None:
                merchant = getattr(target.campaign, 'merchant', None)
        target_type, target_id = _target_identity(target)
        return AuditLog.objects.create(
            actor=actor,
            merchant=merchant,
            action=str(action)[:120],
            target_type=target_type[:120],
            target_id=target_id[:120],
            metadata=_safe_metadata(metadata),
            ip_address=_client_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:255],
        )
    except Exception:
        logger.exception('Audit logging failed for action=%s', action)
        return None
