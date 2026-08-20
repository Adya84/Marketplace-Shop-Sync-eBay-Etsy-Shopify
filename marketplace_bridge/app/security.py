from __future__ import annotations

import base64
import hashlib
import hmac
import os


class SecretBox:
    """Small authenticated secret wrapper using only the Python standard library.

    This protects stored tokens from casual disclosure. The installation key is
    generated once and kept beside the database in the add-on's private config.
    """

    def __init__(self, key: bytes):
        self.key = key

    @classmethod
    def from_file(cls, path):
        if not path.exists():
            path.write_bytes(os.urandom(32))
            os.chmod(path, 0o600)
        return cls(path.read_bytes())

    def encrypt(self, value: str) -> str:
        raw = value.encode()
        nonce = os.urandom(16)
        stream = self._stream(nonce, len(raw))
        ciphertext = bytes(a ^ b for a, b in zip(raw, stream))
        tag = hmac.new(self.key, nonce + ciphertext, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(nonce + tag + ciphertext).decode()

    def decrypt(self, token: str) -> str:
        packed = base64.urlsafe_b64decode(token.encode())
        nonce, tag, ciphertext = packed[:16], packed[16:48], packed[48:]
        expected = hmac.new(self.key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("Stored credential failed authentication")
        stream = self._stream(nonce, len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, stream)).decode()

    def _stream(self, nonce: bytes, length: int) -> bytes:
        blocks = []
        counter = 0
        while sum(map(len, blocks)) < length:
            blocks.append(hmac.new(self.key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
            counter += 1
        return b"".join(blocks)[:length]


