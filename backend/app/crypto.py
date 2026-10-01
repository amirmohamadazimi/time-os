"""Encryption at rest for secrets the app stores (calendar feed links, later OAuth tokens).

Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from ``TIMEOS_SECRET_KEY``. Without that
variable a random secret is generated once into ``TIMEOS_SECRET_KEY_FILE`` (mode 0600), which suits a
local install; hosted setups set the variable so the key survives redeploys.
"""

import base64
import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Config, get_config
from app.errors import DomainError

log = logging.getLogger("timeos.crypto")


class SecretUnreadable(DomainError):
    code = "secret_unreadable"
    status_code = 409


def load_secret(config: Config) -> str:
    if config.secret_key:
        return config.secret_key
    path = Path(config.secret_key_file)
    if path.is_file():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # another process created it first
        return path.read_text().strip()
    with os.fdopen(fd, "w") as fh:
        fh.write(value)
    log.warning("TIMEOS_SECRET_KEY is not set; generated an encryption key in %s (back it up)", path)
    return value


@lru_cache(maxsize=4)
def _fernet(secret: str) -> Fernet:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"timeos/fernet/v1")
    key = hkdf.derive(secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: str, config: Config | None = None) -> str:
    return _fernet(load_secret(config or get_config())).encrypt(plaintext.encode()).decode()


def decrypt(token: str, config: Config | None = None) -> str:
    try:
        return _fernet(load_secret(config or get_config())).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretUnreadable(
            "a stored secret can no longer be decrypted (TIMEOS_SECRET_KEY changed); reconnect it"
        ) from exc
