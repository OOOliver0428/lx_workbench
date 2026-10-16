import base64
import hashlib
import hmac
import json
import re

from cryptography.fernet import Fernet

from app.phone.config import PhoneSettings


def normalize_phone(value: str) -> str:
    number = value.strip()
    if number.startswith("+86"):
        number = number[3:]
    if not re.fullmatch(r"1[3-9][0-9]{9}", number):
        raise ValueError("请输入中国大陆 11 位手机号")
    return "+86" + number


class PhoneCrypto:
    def __init__(self, settings: PhoneSettings):
        raw_keys = json.loads(settings.encryption_keys.get_secret_value())
        if not isinstance(raw_keys, dict) or not raw_keys:
            raise ValueError("phone encryption keys unavailable")
        self.keys = {}
        self.checks = {}
        for key_id, key in raw_keys.items():
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", key_id):
                raise ValueError("invalid phone key id")
            decoded = base64.b64decode(key, altchars=b"-_", validate=True)
            if len(decoded) != 32:
                raise ValueError("invalid phone encryption key")
            self.keys[key_id] = Fernet(key)
            self.checks["enc:" + key_id] = hmac.new(
                decoded,
                b"lx:phone:encryption-key-check:v1",
                hashlib.sha256,
            ).hexdigest()
        self.active = settings.active_key_id
        if self.active not in self.keys:
            raise ValueError("active phone key unavailable")
        self.lookup_key = base64.b64decode(
            settings.lookup_key.get_secret_value(),
            altchars=b"-_",
            validate=True,
        )
        if len(self.lookup_key) != 32 or any(
            self.lookup_key == base64.urlsafe_b64decode(key) for key in raw_keys.values()
        ):
            raise ValueError("phone lookup key must be independent")
        self.checks["lookup"] = hmac.new(
            self.lookup_key,
            b"lx:phone:lookup-key-check:v1",
            hashlib.sha256,
        ).hexdigest()

    def fingerprint(self, phone: str) -> str:
        return hmac.new(
            self.lookup_key,
            b"lx:phone:lookup:v1\0" + phone.encode(),
            hashlib.sha256,
        ).hexdigest()

    def encrypt(self, phone: str, owner: str) -> tuple[str, str]:
        payload = json.dumps({"phone": phone, "owner": owner, "v": 1}).encode()
        return self.keys[self.active].encrypt(payload).decode(), self.active

    def decrypt(self, ciphertext: str, key_id: str, owner: str, fingerprint: str) -> str:
        payload = json.loads(self.keys[key_id].decrypt(ciphertext.encode()))
        phone = normalize_phone(payload["phone"])
        if (
            payload.get("v") != 1
            or payload["owner"] != owner
            or not hmac.compare_digest(
                self.fingerprint(phone),
                fingerprint,
            )
        ):
            raise ValueError("invalid phone ciphertext context")
        return phone
