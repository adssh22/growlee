import hashlib
from urllib.parse import urlparse


def short_identifier(value, *, visible: int = 6) -> str:
    value = str(value or '').strip()
    if not value:
        return ''
    if len(value) <= visible:
        return value
    return f'…{value[-visible:]}'


def stable_hash(value, *, length: int = 12) -> str:
    value = str(value or '').strip()
    if not value:
        return ''
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:length]


def safe_url_summary(url: str) -> dict:
    parsed = urlparse(str(url or '').strip())
    return {
        'scheme': parsed.scheme or 'relative',
        'host': parsed.hostname or '',
        'path_present': bool(parsed.path),
    }
