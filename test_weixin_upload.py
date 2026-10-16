import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weixin_upload import WeixinUploadError, _encrypt, upload_media


class FakeApi:
    def __init__(self, result=None):
        self.result = result or {
            "upload_full_url": "https://novac2c.cdn.weixin.qq.com/c2c/upload?id=test"
        }
        self.request = None

    def get_upload_url(self, **kwargs):
        self.request = kwargs
        return self.result


class FakeResponse:
    status = 200

    def __init__(self, download_parameter="download-param"):
        self.headers = {"x-encrypted-param": download_parameter}

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class WeixinUploadTests(unittest.TestCase):
    def test_encrypt_uses_pkcs7_block_padding(self):
        ciphertext = _encrypt(b"hello", b"1" * 16)
        self.assertEqual(len(ciphertext), 16)
        self.assertNotEqual(ciphertext, b"hello")

    def test_upload_requests_and_posts_encrypted_media(self):
        api = FakeApi()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "voice.mp3"
            path.write_bytes(b"audio-data")
            with patch("weixin_upload.urllib.request.urlopen", return_value=FakeResponse()) as opened:
                result = upload_media(api, path, "owner", media_type=3)
        self.assertEqual(api.request["media_type"], 3)
        self.assertEqual(api.request["raw_size"], 10)
        self.assertEqual(api.request["cipher_size"], 16)
        self.assertEqual(result.download_parameter, "download-param")
        request = opened.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertNotEqual(request.data, b"audio-data")

    def test_upload_rejects_non_official_full_url(self):
        api = FakeApi({"upload_full_url": "https://example.com/upload"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "voice.mp3"
            path.write_bytes(b"audio")
            with self.assertRaisesRegex(WeixinUploadError, "官方"):
                upload_media(api, path, "owner")

    def test_upload_requires_download_parameter(self):
        api = FakeApi()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "voice.mp3"
            path.write_bytes(b"audio")
            with (
                patch("weixin_upload.urllib.request.urlopen", return_value=FakeResponse("")),
                patch("weixin_upload.time.sleep"),
                self.assertRaisesRegex(WeixinUploadError, "下载参数"),
            ):
                upload_media(api, path, "owner")


if __name__ == "__main__":
    unittest.main()
