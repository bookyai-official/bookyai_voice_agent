"""Credential wire format shared with accounts.meta_security (MultiFernet)."""
import hashlib
import json
from datetime import timezone

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from core.config import settings


class MetaSecurityError(Exception):
    pass


def cipher():
    value = settings.META_CREDENTIAL_ENCRYPTION_KEYS
    keys = [key.strip() for key in value.split(',') if key.strip()] if isinstance(value, str) else value
    try:
        if not keys:
            raise ValueError()
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError):
        raise MetaSecurityError('Meta credential encryption is not configured.') from None


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except (ValueError, InvalidToken, UnicodeError):
        raise MetaSecurityError('Meta credentials could not be decrypted.') from None


def encrypt_payload(value):
    return encrypt(json.dumps(value, separators=(',', ':')))


def digest(parts):
    return hashlib.sha256(json.dumps(parts, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
