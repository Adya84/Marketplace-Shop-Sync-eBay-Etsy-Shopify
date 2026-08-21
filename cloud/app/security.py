from __future__ import annotations

import base64
import hashlib
import json
import secrets

from argon2 import PasswordHasher
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except Exception:
        return False


def _key() -> bytes:
    configured = get_settings().token_encryption_key.strip()
    if configured:
        try:
            key = base64.urlsafe_b64decode(configured.encode())
            if len(key) == 32:
                return key
        except Exception:
            pass
    if get_settings().env == "development":
        return hashlib.sha256(get_settings().session_secret.encode()).digest()
    raise RuntimeError("SHOPSYNC_TOKEN_ENCRYPTION_KEY must be a urlsafe-base64 encoded 32-byte key")


def encrypt_json(payload: dict) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, json.dumps(payload, separators=(",", ":")).encode(), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt_json(value: str) -> dict:
    raw = base64.urlsafe_b64decode(value.encode())
    data = AESGCM(_key()).decrypt(raw[:12], raw[12:], None)
    return json.loads(data.decode())


def new_csrf() -> str:
    return secrets.token_urlsafe(32)
