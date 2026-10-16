from __future__ import annotations

import base64
import json
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.models import AuditEvent, AuthSession, PhoneChallenge, User, utc_now
from app.phone.config import PhoneSettings
from app.phone.crypto import PhoneCrypto
from app.phone.service import PhoneService
from tests.conftest import TEST_PASSWORD
from tests.conftest import login as core_login

BASE = "/api/v1/profile/phone"
PHONE = "13800138000"
OTHER = "13900139000"


def login(client, name):
    token = core_login(client, name)
    client.headers["X-CSRF-Token"] = token
    return token


class FakeProvider:
    def __init__(self):
        self.sent = []
        self.checked = []
        self.captcha_ok = True
        self.failure = None
        self.on_verify = None
        self.on_send = None

    def verify_captcha(self, token):
        return self.captcha_ok and token == "test-captcha"

    def send(self, phone, challenge_id):
        self.sent.append((phone, challenge_id))
        if self.on_send:
            self.on_send()
        if self.failure:
            raise RuntimeError(self.failure)

    def verify(self, phone, challenge_id, code):
        self.checked.append((phone, challenge_id))
        if self.on_verify:
            self.on_verify()
        if self.failure:
            raise RuntimeError(self.failure)
        return code == "123456"


@pytest.fixture
def phone_api(api):
    settings = PhoneSettings(
        _env_file=None,
        enabled=True,
        encryption_keys=json.dumps({"v1": Fernet.generate_key().decode()}),
        active_key_id="v1",
        lookup_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        access_key_id="test-access",
        access_key_secret="test-secret",
        captcha_prefix="test-prefix",
        captcha_scene_id="test-scene",
        sms_sign_name="test-sign",
        sms_template_code="test-template",
        sms_scheme_name="test-phone",
    )
    provider = FakeProvider()
    service = api["app"].state.phone_service
    service.settings, service.provider = settings, provider
    auth = login(api["client"], "member")
    return {**api, "settings": settings, "provider": provider, "service": service, "auth": auth}


def send(env, number=PHONE):
    return env["client"].post(
        BASE + "/challenges",
        json={
            "phone_number": number,
            "captcha_verify_param": "test-captcha",
        },
    )


def verify(env, challenge, code="123456", password=None):
    status = env["client"].get(BASE).json()
    body = {"sms_code": code, "revision": status["revision"]}
    if password is not None:
        body["current_password"] = password
    return env["client"].post(BASE + f"/challenges/{challenge}/verify", json=body)


def age_requests(env):
    with env["app"].state.session_factory.begin() as db:
        for row in db.scalars(select(PhoneChallenge)):
            row.created_at -= timedelta(seconds=61)


def test_binding_encrypts_every_persistent_copy_and_is_private(phone_api, tmp_path):
    env = phone_api
    response = send(env)
    assert response.status_code == 200, response.text
    challenge = response.json()["challenge_id"]
    response = verify(env, challenge)
    assert response.status_code == 200, response.text
    assert response.json()["phone_masked"] == "138****8000"
    assert "phone" not in json.dumps(env["client"].get("/api/v1/auth/me").json()["user"])
    with env["app"].state.session_factory() as db:
        user = db.scalar(select(User).where(User.login_name == "member"))
        record = db.get(PhoneChallenge, challenge)
        crypto = PhoneCrypto(env["settings"])
        assert user.phone_ciphertext != record.phone_ciphertext
        assert user.phone_lookup_hash == record.phone_lookup_hash
        assert (
            crypto.decrypt(
                user.phone_ciphertext, user.phone_key_id, "user:" + user.id, user.phone_lookup_hash
            )
            == "+86" + PHONE
        )
        assert record.state == "completed"
        assert user.phone_verified_at is not None
        audits = list(
            db.scalars(select(AuditEvent).where(AuditEvent.action == "profile.phone.bind"))
        )
        assert len(audits) == 1
        assert audits[0].before_data is None and audits[0].after_data is None
    # SQLite main file, WAL, SQL export, and SQLite backup never received the clear phone.
    path = env["app"].state.engine.url.database
    with sqlite3.connect(path) as db, sqlite3.connect(tmp_path / "backup.db") as backup:
        assert PHONE not in "\n".join(db.iterdump())
        db.backup(backup)
    from pathlib import Path

    for item in (Path(path), Path(path + "-wal"), tmp_path / "backup.db"):
        if item.exists():
            assert PHONE.encode() not in item.read_bytes()
    assert verify(env, challenge).status_code == 200
    assert len(env["provider"].checked) == 1
    login(env["client"], "admin")
    users = env["client"].get("/api/v1/users").json()
    assert "phone" not in json.dumps(users)
    assert PHONE not in env["client"].get("/api/v1/audit-events").text
    assert send(env).status_code == 409


def test_invalid_codes_are_committed_and_survive_runtime_recreation(phone_api):
    env = phone_api
    challenge = send(env).json()["challenge_id"]
    for _ in range(5):
        assert verify(env, challenge, "000000").status_code == 400
    with env["app"].state.session_factory() as db:
        row = db.get(PhoneChallenge, challenge)
        assert row.attempts == 5 and row.state == "invalid"
    old = env["app"].state.phone_service
    env["app"].state.phone_service = PhoneService(old.factory, env["settings"], env["provider"])
    old.close()
    assert verify(env, challenge).status_code == 409
    assert send(env).status_code == 429


def test_change_requires_password_and_preserves_old_number(phone_api):
    env = phone_api
    first = send(env).json()["challenge_id"]
    assert verify(env, first).status_code == 200
    age_requests(env)
    second = send(env, OTHER).json()["challenge_id"]
    assert verify(env, second, password="wrong-password").status_code == 400
    assert env["client"].get(BASE).json()["phone_masked"] == "138****8000"
    assert len(env["provider"].checked) == 1
    assert verify(env, second, password=TEST_PASSWORD).status_code == 200
    assert env["client"].get(BASE).json()["phone_masked"] == "139****9000"
    # Replaying a prior successful challenge never restores the old number.
    assert verify(env, first).json()["phone_masked"] == "139****9000"


def test_captcha_and_provider_failure_fail_closed_and_redact(phone_api, caplog):
    env = phone_api
    env["provider"].captcha_ok = False
    assert send(env).status_code == 400
    assert not env["provider"].sent
    age_requests(env)
    env["provider"].captcha_ok = True
    env["provider"].failure = PHONE + " test-secret test-captcha"
    assert send(env).status_code == 503
    assert len(env["provider"].sent) == 1
    assert PHONE not in caplog.text and "test-secret" not in caplog.text
    assert send(env).status_code == 429
    assert env["client"].get("/api/v1/auth/me").status_code == 200
    assert env["client"].get(BASE).json()["bound"] is False


def test_wrong_keys_never_reset_uniqueness_or_binding_state(phone_api):
    env = phone_api
    challenge = send(env).json()["challenge_id"]
    assert verify(env, challenge).status_code == 200
    original = env["settings"].lookup_key
    env["settings"].lookup_key = SecretStr(Fernet.generate_key().decode())
    status = env["client"].get(BASE).json()
    assert status["bound"] and status["availability"] == "unavailable"
    assert status["phone_masked"] is None
    assert send(env, OTHER).status_code == 503
    assert env["client"].get("/api/v1/auth/me").status_code == 200
    env["settings"].lookup_key = original
    old_keys = env["settings"].encryption_keys
    env["settings"].encryption_keys = SecretStr(json.dumps({"v1": Fernet.generate_key().decode()}))
    assert env["client"].get(BASE).json()["availability"] == "unavailable"
    env["settings"].encryption_keys = old_keys
    assert env["client"].get(BASE).json()["availability"] == "ready"


def test_encryption_rotation_preserves_fingerprint_and_cooldown(phone_api):
    env = phone_api
    challenge = send(env).json()["challenge_id"]
    old_crypto = PhoneCrypto(env["settings"])
    keys = json.loads(env["settings"].encryption_keys.get_secret_value())
    keys["v2"] = Fernet.generate_key().decode()
    env["settings"].encryption_keys = SecretStr(json.dumps(keys))
    env["settings"].active_key_id = "v2"
    assert verify(env, challenge).status_code == 200
    with env["app"].state.session_factory() as db:
        user = db.scalar(select(User).where(User.login_name == "member"))
        assert user.phone_key_id == "v2"
        assert user.phone_lookup_hash == old_crypto.fingerprint("+86" + PHONE)
    assert send(env, OTHER).status_code == 429
    del keys["v1"]
    env["settings"].encryption_keys = SecretStr(json.dumps(keys))
    assert env["client"].get(BASE).json()["availability"] == "unavailable"


def test_expiry_cross_user_cross_session_and_csrf(phone_api):
    env = phone_api
    response = send(env)
    challenge = response.json()["challenge_id"]
    login(env["client"], "member2")
    assert verify(env, challenge).status_code == 404
    login(env["client"], "member")
    assert verify(env, challenge).status_code == 404
    env["client"].headers.pop("X-CSRF-Token", None)
    assert send(env, OTHER).status_code == 403


def test_validation_response_does_not_echo_sensitive_input(phone_api):
    env = phone_api
    response = env["client"].post(
        BASE + "/challenges",
        json={
            "phone_number": PHONE,
            "captcha_verify_param": "secret-captcha",
            "unexpected": PHONE,
        },
    )
    assert response.status_code == 422
    assert PHONE not in response.text and "secret-captcha" not in response.text


def test_user_revision_change_during_cloud_verify_preserves_old_state(phone_api):
    env = phone_api
    challenge = send(env).json()["challenge_id"]

    def change_user():
        with env["app"].state.session_factory.begin() as db:
            user = db.scalar(select(User).where(User.login_name == "member"))
            user.revision += 1

    env["provider"].on_verify = change_user
    assert verify(env, challenge).status_code == 409
    assert not env["client"].get(BASE).json()["bound"]


def test_revoked_session_during_send_cannot_complete(phone_api):
    env = phone_api

    def revoke():
        with env["app"].state.session_factory.begin() as db:
            for auth in db.scalars(select(AuthSession)):
                auth.revoked_at = utc_now()

    env["provider"].on_send = revoke
    assert send(env).status_code == 401
    with env["app"].state.session_factory() as db:
        assert db.scalar(select(PhoneChallenge)).state == "invalid"


def test_repeated_send_and_verify_are_mutually_exclusive_without_holding_db_lock(phone_api):
    env = phone_api
    entered, release = threading.Event(), threading.Event()

    def block():
        entered.set()
        assert release.wait(5)

    env["provider"].on_send = block
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(send, env)
        assert entered.wait(5)
        try:
            response = send(env, OTHER)
            assert response.status_code == 409
            # An unrelated core write succeeds while the provider is blocked.
            with env["app"].state.session_factory.begin() as db:
                user = db.scalar(select(User).where(User.login_name == "member2"))
                user.avatar_key = "flat-01"
        finally:
            release.set()
        assert pending.result().status_code == 200
    assert len(env["provider"].sent) == 1


def test_disabled_and_invalid_configuration_do_not_break_core(phone_api, monkeypatch):
    env = phone_api
    env["settings"].enabled = False
    assert env["client"].get(BASE).json()["availability"] == "disabled"
    assert send(env).status_code == 503
    env["service"].settings = None
    monkeypatch.setenv("MVP_PHONE_VERIFICATION_ENABLED", "invalid")
    assert env["client"].get(BASE).json()["availability"] == "unavailable"
    assert env["client"].get("/api/v1/auth/me").status_code == 200


def test_sdk_adapter_checks_business_result_and_never_returns_code(phone_api):
    from app.phone.provider import AliyunPhoneProvider

    provider = AliyunPhoneProvider(phone_api["settings"])
    requests = []

    def send_response(req, options):
        requests.append(req)
        assert options.autoretry is False
        return SimpleNamespace(body=SimpleNamespace(success=True, code="OK"))

    provider.sms.send_sms_verify_code_with_options = send_response
    provider.send("+86" + PHONE, "challenge")
    assert requests[0].return_verify_code is False
    assert requests[0].auto_retry == 0
    assert requests[0].phone_number == PHONE
    assert json.loads(requests[0].template_param)["code"] == "##code##"
    provider.sms.check_sms_verify_code_with_options = lambda *_: SimpleNamespace(
        body=SimpleNamespace(
            success=True, code="OK", model=SimpleNamespace(verify_result="UNKNOWN")
        ),
    )
    assert not provider.verify("+86" + PHONE, "challenge", "123456")
    provider.captcha.verify_intelligent_captcha_with_options = lambda *_: SimpleNamespace(
        body=SimpleNamespace(success=True, result=SimpleNamespace(verify_result=False)),
    )
    assert not provider.verify_captcha("token")


def test_expired_and_superseded_challenges_cannot_bind(phone_api):
    env = phone_api
    first = send(env).json()["challenge_id"]
    with env["app"].state.session_factory.begin() as db:
        db.get(PhoneChallenge, first).expires_at = utc_now() - timedelta(seconds=1)
    assert verify(env, first).status_code == 409
    age_requests(env)
    second = send(env, OTHER).json()["challenge_id"]
    assert verify(env, first).status_code == 409
    assert verify(env, second).status_code == 200
    assert env["provider"].checked == [("+86" + OTHER, second)]


def test_timeout_lease_recovers_and_late_response_cannot_change_new_state(phone_api):
    env = phone_api

    def expire_lease():
        with env["app"].state.session_factory.begin() as db:
            row = db.scalar(select(PhoneChallenge).where(PhoneChallenge.state == "sending"))
            row.operation_until = utc_now() - timedelta(seconds=1)

    env["provider"].on_send = expire_lease
    assert send(env).status_code == 409
    env["provider"].on_send = None
    age_requests(env)
    second = send(env, OTHER)
    assert second.status_code == 200
    assert verify(env, second.json()["challenge_id"]).status_code == 200


def test_encrypted_context_tamper_is_rejected(phone_api):
    env = phone_api
    challenge = send(env).json()["challenge_id"]
    with env["app"].state.session_factory.begin() as db:
        row = db.get(PhoneChallenge, challenge)
        row.phone_ciphertext, row.phone_key_id = PhoneCrypto(env["settings"]).encrypt(
            "+86" + PHONE, "user:someone-else"
        )
    assert verify(env, challenge).status_code == 503
    assert not env["provider"].checked
    assert env["client"].get("/api/v1/auth/me").status_code == 200


def test_number_limits_are_independent_of_user_and_rotating_target(phone_api):
    env = phone_api
    env["settings"].number_hour_limit = 1
    env["settings"].user_hour_limit = 1
    assert send(env).status_code == 200
    age_requests(env)
    assert send(env, OTHER).status_code == 429
    login(env["client"], "member2")
    assert send(env).status_code == 429
    assert len(env["provider"].sent) == 1


def test_concurrent_verify_calls_provider_once(phone_api):
    env = phone_api
    challenge = send(env).json()["challenge_id"]
    entered, release = threading.Event(), threading.Event()

    def block():
        entered.set()
        assert release.wait(5)

    env["provider"].on_verify = block
    revision = env["client"].get(BASE).json()["revision"]

    def post_verify():
        return env["client"].post(
            BASE + f"/challenges/{challenge}/verify",
            json={
                "sms_code": "123456",
                "revision": revision,
            },
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(post_verify)
        assert entered.wait(5)
        try:
            assert post_verify().status_code == 409
        finally:
            release.set()
        assert pending.result().status_code == 200
    assert len(env["provider"].checked) == 1


def test_provider_not_ready_does_not_hide_decryptable_bound_number(phone_api):
    env = phone_api
    challenge = send(env).json()["challenge_id"]
    assert verify(env, challenge).status_code == 200
    env["settings"].access_key_secret = SecretStr("")
    result = env["client"].get(BASE).json()
    assert result["availability"] == "unavailable"
    assert result["phone_masked"] == "138****8000"
    env["settings"].enabled = False
    result = env["client"].get(BASE).json()
    assert result["availability"] == "disabled"
    assert result["phone_masked"] == "138****8000"
