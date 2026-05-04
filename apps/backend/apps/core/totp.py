import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    padded = secret + ('=' * ((8 - len(secret) % 8) % 8))
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack('>Q', counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def verify_totp(secret: str, code: str, step: int = 30, window: int = 1) -> bool:
    code = ''.join(ch for ch in (code or '') if ch.isdigit())
    if len(code) != 6:
        return False
    counter = int(time.time() // step)
    return any(hmac.compare_digest(_hotp(secret, counter + drift), code) for drift in range(-window, window + 1))


def provisioning_uri(secret: str, username: str, issuer: str = 'Growlee Control') -> str:
    label = f'{issuer}:{username}'
    return (
        'otpauth://totp/' + quote(label) +
        '?secret=' + quote(secret) +
        '&issuer=' + quote(issuer) +
        '&algorithm=SHA1&digits=6&period=30'
    )
