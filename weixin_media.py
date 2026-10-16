"""安全下载并解密微信 iLink 入站媒体。"""

from __future__ import annotations

import base64
import os
import re
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from conversation_manager import PROJECT_DIR

CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
INBOX_DIR = PROJECT_DIR / "data" / "inbox"
MAX_MEDIA_BYTES = 25 * 1024 * 1024
MAX_MESSAGE_MEDIA_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENTS = 8
VOICE_SUFFIXES = {
    1: ".pcm",
    4: ".spx",
    5: ".amr",
    6: ".silk",
    7: ".mp3",
    8: ".spx",
}


@dataclass(frozen=True)
class MediaAttachment:
    kind: str
    path: Path


def _safe_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        hostname == "weixin.qq.com" or hostname.endswith(".weixin.qq.com")
    ):
        raise ValueError("微信媒体地址不是腾讯官方 HTTPS 域名。")
    return url


def _decode_key(value: str | None, hex_key: str | None = None) -> bytes | None:
    if hex_key and re.fullmatch(r"[0-9a-fA-F]{32}", hex_key):
        return bytes.fromhex(hex_key)
    if not value:
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise ValueError("微信媒体 AES Key 格式错误。") from error
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        try:
            return bytes.fromhex(decoded.decode("ascii"))
        except (UnicodeError, ValueError) as error:
            raise ValueError("微信媒体 AES Key 格式错误。") from error
    raise ValueError("微信媒体 AES Key 长度错误。")


def _decrypt(ciphertext: bytes, key: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    try:
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError as error:
        raise ValueError("微信媒体解密校验失败。") from error


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        _safe_url(url), headers={"User-Agent": "AIProject/1.1"}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_MEDIA_BYTES + 1)
    if len(data) > MAX_MEDIA_BYTES:
        raise ValueError("微信媒体超过 25 MB，已拒绝下载。")
    return data


def _safe_filename(name: str, fallback: str) -> str:
    name = Path(str(name or fallback).replace("\x00", "")).name
    name = re.sub(r"[^\w.\-()\u4e00-\u9fff]", "_", name, flags=re.UNICODE)
    return name[:120] or fallback


def _item_details(item: dict):
    item_type = item.get("type")
    mapping = {
        2: ("image", "image_item", "image.jpg"),
        3: ("voice", "voice_item", "voice.dat"),
        4: ("file", "file_item", "file.bin"),
        5: ("video", "video_item", "video.mp4"),
    }
    if item_type not in mapping:
        return None
    kind, field, fallback = mapping[item_type]
    detail = item.get(field) or {}
    media = detail.get("media") or {}
    url = str(media.get("full_url") or "").strip()
    if not url:
        parameter = str(media.get("encrypt_query_param") or "").strip()
        if not parameter:
            return None
        url = f"{CDN_BASE_URL}/download?{urllib.parse.urlencode({'encrypted_query_param': parameter})}"
    key = _decode_key(media.get("aes_key"), detail.get("aeskey") if kind == "image" else None)
    if key is None and kind != "image":
        return None
    if kind == "voice":
        suffix = VOICE_SUFFIXES.get(detail.get("encode_type"), ".dat")
        filename = f"voice{suffix}"
    else:
        filename = detail.get("file_name") if kind == "file" else fallback
    return kind, url, key, _safe_filename(filename, fallback)


def download_media_items(message: dict, inbox=INBOX_DIR) -> list[MediaAttachment]:
    inbox = Path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    message_id = re.sub(r"[^A-Za-z0-9_-]", "", str(message.get("message_id") or "msg"))[:64]
    attachments = []
    total_downloaded = 0
    for index, item in enumerate((message.get("item_list") or [])[:MAX_ATTACHMENTS]):
        details = _item_details(item)
        if details is None:
            continue
        kind, url, key, filename = details
        ciphertext = _download(url)
        if total_downloaded + len(ciphertext) > MAX_MESSAGE_MEDIA_BYTES:
            break
        total_downloaded += len(ciphertext)
        plaintext = _decrypt(ciphertext, key) if key else ciphertext
        destination = inbox / f"{message_id}_{index}_{filename}"
        descriptor, temporary = tempfile.mkstemp(prefix="weixin_", suffix=".tmp", dir=inbox)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(plaintext)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        attachments.append(MediaAttachment(kind, destination))
    return attachments
