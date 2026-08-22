"""API Key 的 AES-256-GCM 加密。"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from api import config


NONCE_SIZE = 12


def _master_key() -> bytes:
    """读取 base64 编码的 32-byte AES 密钥。"""
    encoded = config.aes_key()
    if not encoded:
        raise RuntimeError("AES_KEY is not configured")
    try:
        key = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("AES_KEY must be urlsafe-base64 encoded") from exc
    if len(key) != 32:
        raise ValueError("AES_KEY must decode to exactly 32 bytes")
    return key


def encrypt_key(value: str) -> str:
    """使用随机 nonce 加密 API Key，返回可存储的 base64 密文。"""
    if not value:
        raise ValueError("key value cannot be empty")
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(_master_key()).encrypt(nonce, value.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_key(encoded: str) -> str:
    """解密 API Key；认证标签失败会抛出 ValueError。"""
    try:
        payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
        if len(payload) <= NONCE_SIZE:
            raise ValueError("ciphertext is too short")
        nonce, ciphertext = payload[:NONCE_SIZE], payload[NONCE_SIZE:]
        return AESGCM(_master_key()).decrypt(nonce, ciphertext, None).decode("utf-8")
    except (InvalidTag, ValueError, UnicodeError) as exc:
        raise ValueError("invalid encrypted API key") from exc


def mask_key(value: str) -> str:
    """仅保留末四位用于界面识别。"""
    return "****" if len(value) <= 4 else "****" + value[-4:]
