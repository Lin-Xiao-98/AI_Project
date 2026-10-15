import base64
import os
import unittest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from weixin_media import _decode_key, _decrypt, _safe_url


class WeixinMediaTests(unittest.TestCase):
    def test_key_encodings_and_decryption(self):
        key = os.urandom(16)
        plaintext = b"private media payload"
        padder = PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        self.assertEqual(_decode_key(base64.b64encode(key).decode()), key)
        encoded_hex = base64.b64encode(key.hex().encode()).decode()
        self.assertEqual(_decode_key(encoded_hex), key)
        self.assertEqual(_decode_key(None, key.hex()), key)
        self.assertEqual(_decrypt(ciphertext, key), plaintext)

    def test_only_official_cdn_urls_are_allowed(self):
        valid = "https://novac2c.cdn.weixin.qq.com/c2c/download?id=1"
        self.assertEqual(_safe_url(valid), valid)
        with self.assertRaises(ValueError):
            _safe_url("https://example.com/media")


if __name__ == "__main__":
    unittest.main()
