"""微信 iLink 官方 CDN 的出站媒体上传。

只处理本地文件的加密上传，不负责决定消息类型或自动播放。
"""

from __future__ import annotations

import hashlib
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
MAX_OUTBOUND_MEDIA_BYTES = 25 * 1024 * 1024
UPLOAD_RETRIES = 3


class WeixinUploadError(RuntimeError):
    """微信 CDN 上传失败。"""


@dataclass(frozen=True)
class UploadedMedia:
    download_parameter: str
    aes_key_hex: str
    plain_size: int
    cipher_size: int


def _official_upload_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        hostname == "weixin.qq.com" or hostname.endswith(".weixin.qq.com")
    ):
        raise WeixinUploadError("微信上传地址不是腾讯官方 HTTPS 域名。")
    return value


def _encrypt(plaintext: bytes, key: bytes) -> bytes:
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def upload_media(api, path: str | Path, to_user_id: str, media_type: int = 3) -> UploadedMedia:
    """按腾讯 iLink 协议加密上传一个文件并返回可发送的媒体引用。"""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("找不到要发送的媒体文件。")
    plaintext = source.read_bytes()
    if not plaintext:
        raise ValueError("不能发送空文件。")
    if len(plaintext) > MAX_OUTBOUND_MEDIA_BYTES:
        raise ValueError("单个微信媒体文件不能超过 25 MB。")
    if media_type not in {1, 2, 3, 4}:
        raise ValueError("微信媒体类型无效。")

    key = secrets.token_bytes(16)
    key_hex = key.hex()
    file_key = secrets.token_hex(16)
    ciphertext = _encrypt(plaintext, key)
    upload_info = api.get_upload_url(
        file_key=file_key,
        media_type=media_type,
        to_user_id=to_user_id,
        raw_size=len(plaintext),
        raw_md5=hashlib.md5(plaintext).hexdigest(),  # noqa: S324 - 协议字段，不用于安全校验
        cipher_size=len(ciphertext),
        aes_key_hex=key_hex,
    )
    upload_url = str(upload_info.get("upload_full_url") or "").strip()
    if not upload_url:
        parameter = str(upload_info.get("upload_param") or "").strip()
        if not parameter:
            raise WeixinUploadError("微信服务器没有返回媒体上传地址。")
        upload_url = (
            f"{CDN_BASE_URL}/upload?"
            + urllib.parse.urlencode(
                {"encrypted_query_param": parameter, "filekey": file_key}
            )
        )
    upload_url = _official_upload_url(upload_url)

    last_error = None
    for attempt in range(UPLOAD_RETRIES):
        request = urllib.request.Request(
            upload_url,
            data=ciphertext,
            headers={"Content-Type": "application/octet-stream"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = getattr(response, "status", response.getcode())
                download_parameter = str(
                    response.headers.get("x-encrypted-param") or ""
                ).strip()
                if status != 200:
                    raise WeixinUploadError(f"微信 CDN 上传失败：HTTP {status}")
                if not download_parameter:
                    raise WeixinUploadError("微信 CDN 没有返回下载参数。")
                return UploadedMedia(
                    download_parameter,
                    key_hex,
                    len(plaintext),
                    len(ciphertext),
                )
        except urllib.error.HTTPError as error:
            if 400 <= error.code < 500:
                raise WeixinUploadError(f"微信 CDN 拒绝上传：HTTP {error.code}") from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, OSError, WeixinUploadError) as error:
            last_error = error
        if attempt + 1 < UPLOAD_RETRIES:
            time.sleep(0.2 * (attempt + 1))
    raise WeixinUploadError(f"微信 CDN 上传失败：{last_error}") from last_error

