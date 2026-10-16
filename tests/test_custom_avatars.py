from __future__ import annotations

import asyncio
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from PIL import Image
from sqlalchemy import select

from app.custom_avatars.config import MAX_REQUEST_BYTES, MAX_UPLOAD_BYTES, AvatarSettings
from app.custom_avatars.images import AvatarCrop, process_image
from app.custom_avatars.service import AvatarService
from app.errors import AppError
from app.models import AuditEvent, AuthSession, AvatarAsset, User, utc_now
from tests.conftest import login

BASE = "/api/v1/profile/avatar"


def picture(format="PNG", size=(800, 600), **kwargs):
    stream = io.BytesIO()
    image = Image.new("RGB", size, "#e55633")
    image.save(stream, format=format, **kwargs)
    return stream.getvalue()


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.gets = 0
        self.deleted = []
        self.on_put = None
        self.put_failure = False
        self.delete_failure = False
        self.version_id = None
        self.deleted_versions = []

    def put(self, bucket, region, key, data):
        self.objects[bucket, region, key] = data
        if self.on_put:
            self.on_put()
        if self.put_failure:
            raise RuntimeError("secret-key-must-never-appear-in-response-or-logs")
        return self.version_id

    def get(self, bucket, region, key):
        self.gets += 1
        return self.objects[bucket, region, key]

    def delete(self, bucket, region, key, version_id):
        if self.delete_failure:
            raise RuntimeError("temporary deletion failure")
        self.deleted.append(key)
        self.deleted_versions.append(version_id)
        self.objects.pop((bucket, region, key), None)


@pytest.fixture
def avatar_api(api):
    service = api["app"].state.avatar_service
    settings = AvatarSettings(
        _env_file=None,
        enabled=True,
        secret_id="test-id",
        secret_key="test-secret",
        bucket="avatars-test-1234567890",
        region="ap-guangzhou",
    )
    storage = FakeStorage()
    service.settings, service.storage = settings, storage
    with api["app"].state.session_factory.begin() as db:
        user = db.get(User, api["users"]["member"])
        user.phone_ciphertext = "test-encrypted-data"
        user.phone_key_id = "test-key"
        user.phone_lookup_hash = "f" * 64
        user.phone_verified_at = utc_now()
    csrf = login(api["client"], "member")
    api["client"].headers["X-CSRF-Token"] = csrf
    return {**api, "service": service, "storage": storage, "settings": settings}


def upload(env, *, data=None, revision=None, crop=None):
    if revision is None:
        with env["app"].state.session_factory() as db:
            revision = db.get(User, env["users"]["member"]).revision
    return env["client"].post(
        BASE + "/upload",
        files={
            "file": ("private-original-name.png", picture() if data is None else data, "image/png")
        },
        data={
            "revision": str(revision),
            "crop": json.dumps({"x": 0.125, "y": 0, "size": 1} if crop is None else crop),
        },
    )


def assets(env):
    with env["app"].state.session_factory() as db:
        return list(db.scalars(select(AvatarAsset).order_by(AvatarAsset.created_at)))


def expire_assets(env):
    with env["app"].state.session_factory.begin() as db:
        for asset in db.scalars(select(AvatarAsset).where(AvatarAsset.cleanup_after.is_not(None))):
            asset.cleanup_after = utc_now() - timedelta(seconds=1)


def test_default_module_is_disabled_and_core_avatars_still_work(api):
    client = api["client"]
    csrf = login(client, "member")
    client.headers["X-CSRF-Token"] = csrf
    status = client.get(BASE + "/status")
    assert status.status_code == 200
    assert status.json()["availability"] == "disabled"
    assert status.json()["can_upload"] is False
    assert client.get("/api/v1/profile/avatars").status_code == 200


def test_bound_user_uploads_without_phone_provider_and_all_authenticated_roles_can_view(avatar_api):
    env = avatar_api
    assert (
        env["service"].status(
            env["users"]["member"],
            # Verify the actual endpoint rather than requiring a phone SDK configuration.
            next_session(env),
        )["can_upload"]
        is True
    )
    before = env["client"].get("/api/v1/auth/me").json()["user"]["revision"]
    response = upload(env)
    assert response.status_code == 200, response.text
    user = response.json()
    assert user["revision"] == before + 1
    key = user["avatar_key"]
    assert key.startswith("custom-") and len(key) == 39
    asset = assets(env)[0]
    assert asset.state == "active" and asset.cleanup_after is None
    assert asset.width == asset.height == 512
    assert "private-original-name" not in asset.object_key
    with env["app"].state.session_factory() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "profile.avatar.update"))
        assert audit.after_data["avatarKey"] == key
    for name in ("member", "leader", "admin", "super_admin"):
        login(env["client"], name)
        image = env["client"].get("/api/v1/avatars/" + asset.id)
        assert image.status_code == 200, image.text
        assert image.headers["content-type"] == "image/webp"
        assert image.headers["cache-control"] == "no-store"
        with Image.open(io.BytesIO(image.content)) as decoded:
            assert decoded.size == (512, 512)
            assert not decoded.getexif()
    assert env["storage"].gets == 1
    env["client"].cookies.clear()
    assert env["client"].get("/api/v1/avatars/" + asset.id).status_code == 401


def next_session(env):
    with env["app"].state.session_factory() as db:
        return db.scalar(
            select(AuthSession.id)
            .where(AuthSession.user_id == env["users"]["member"], AuthSession.revoked_at.is_(None))
            .order_by(AuthSession.created_at.desc())
        )


def test_unbound_partial_binding_csrf_and_revision_are_enforced(avatar_api):
    env = avatar_api
    with env["app"].state.session_factory.begin() as db:
        user = db.get(User, env["users"]["member"])
        user.phone_verified_at = None
    assert upload(env).json()["code"] == "AVATAR_PHONE_REQUIRED"
    assert not assets(env)
    with env["app"].state.session_factory.begin() as db:
        user = db.get(User, env["users"]["member"])
        user.phone_verified_at = utc_now()
        user.phone_ciphertext = None
    assert env["client"].get(BASE + "/status").json()["phone_bound"] is False
    assert upload(env).status_code == 403
    env["client"].headers.pop("X-CSRF-Token")
    assert upload(env).json()["code"] == "CSRF_VALIDATION_FAILED"
    env["client"].headers["X-CSRF-Token"] = login(env["client"], "member")
    with env["app"].state.session_factory.begin() as db:
        db.get(User, env["users"]["member"]).phone_ciphertext = "test-encrypted-data"
    assert upload(env, revision=999).status_code == 409
    assert not env["storage"].objects


@pytest.mark.parametrize("change", ["revision", "frozen", "session", "phone"])
def test_upload_rechecks_actor_after_cloud_write_and_keeps_previous_avatar(avatar_api, change):
    env = avatar_api
    with env["app"].state.session_factory.begin() as db:
        db.get(User, env["users"]["member"]).avatar_key = "flat-01"

    def mutate_during_put():
        # This transaction must succeed while the cloud operation is in progress.
        with env["app"].state.session_factory.begin() as db:
            user = db.get(User, env["users"]["member"])
            if change == "revision":
                user.revision += 1
            elif change == "frozen":
                user.is_active = False
            elif change == "phone":
                user.phone_verified_at = None
            else:
                session = db.get(AuthSession, next_session(env))
                session.revoked_at = utc_now()

    env["storage"].on_put = mutate_during_put
    response = upload(env)
    assert response.status_code in {401, 403, 409}, response.text
    with env["app"].state.session_factory() as db:
        assert db.get(User, env["users"]["member"]).avatar_key == "flat-01"
    assert assets(env)[0].state == "pending"
    expire_assets(env)
    assert env["service"].cleanup() == 1
    assert not env["storage"].objects


def test_ambiguous_cloud_failure_is_private_and_scheduled_for_cleanup(avatar_api, caplog):
    env = avatar_api
    env["storage"].put_failure = True
    response = upload(env)
    assert response.status_code == 503
    assert "secret-key-must-never" not in response.text + caplog.text
    assert len(env["storage"].objects) == 1
    expire_assets(env)
    assert env["service"].cleanup() == 1


def test_database_failure_after_upload_does_not_change_profile(avatar_api, monkeypatch):
    env = avatar_api

    def fail_audit(*args, **kwargs):
        raise RuntimeError("transaction failure")

    monkeypatch.setattr("app.custom_avatars.service.record_audit", fail_audit)
    response = upload(env)
    assert response.status_code == 503
    with env["app"].state.session_factory() as db:
        assert db.get(User, env["users"]["member"]).avatar_key == "flat-01"
    assert assets(env)[0].state == "pending"


def test_replacement_retires_old_image_and_cleanup_survives_restart_and_failure(avatar_api):
    env = avatar_api
    first = upload(env).json()["avatar_key"]
    assert upload(env).status_code == 200
    old, current = assets(env)
    assert old.state == "retired" and old.cleanup_after > utc_now() + timedelta(hours=23)
    assert env["client"].get("/api/v1/avatars/" + first[7:]).status_code == 404
    assert env["service"].cleanup() == 0
    expire_assets(env)
    restarted = AvatarService(env["app"].state.session_factory, env["settings"], env["storage"])
    try:
        env["storage"].delete_failure = True
        assert restarted.cleanup() == 0
        assert assets(env)[0].state == "deleting"
        assert len(env["storage"].objects) == 2
        env["storage"].delete_failure = False
        expire_assets(env)
        assert restarted.cleanup() == 1
        assert assets(env)[0].id == current.id
    finally:
        restarted.close()


def test_selecting_preset_retires_custom_and_cannot_reactivate_arbitrary_key(avatar_api):
    env = avatar_api
    user = upload(env).json()
    response = env["client"].patch(
        BASE, json={"revision": user["revision"], "avatar_key": "flat-01"}
    )
    assert response.status_code == 200
    assert assets(env)[0].state == "retired"
    denied = env["client"].patch(
        BASE,
        json={
            "revision": response.json()["revision"],
            "avatar_key": user["avatar_key"],
        },
    )
    assert denied.json()["code"] == "AVATAR_NOT_FOUND"


def test_cleanup_protects_current_reference_even_with_inconsistent_metadata(avatar_api):
    env = avatar_api
    assert upload(env).status_code == 200
    with env["app"].state.session_factory.begin() as db:
        asset = db.scalar(select(AvatarAsset))
        asset.state = "retired"
        asset.cleanup_after = utc_now() - timedelta(seconds=1)
    assert env["service"].cleanup() == 0
    assert assets(env)[0].state == "active"
    assert len(env["storage"].objects) == 1


def test_failed_attempts_are_rate_limited_across_runtime_restarts(avatar_api):
    env = avatar_api
    for _ in range(10):
        assert upload(env, data=b"not a picture").status_code == 400
    restarted = AvatarService(env["app"].state.session_factory, env["settings"], env["storage"])
    env["app"].state.avatar_service = restarted
    try:
        response = upload(env)
        assert response.status_code == 429
        assert response.json()["code"] == "AVATAR_RATE_LIMITED"
        assert not env["storage"].objects
    finally:
        env["app"].state.avatar_service = env["service"]
        restarted.close()


def test_storage_corruption_and_disabled_module_return_controlled_errors(avatar_api):
    env = avatar_api
    user = upload(env).json()
    asset = assets(env)[0]
    env["storage"].objects[asset.bucket, asset.region, asset.object_key] = b"tampered"
    assert env["client"].get("/api/v1/avatars/" + user["avatar_key"][7:]).status_code == 503
    env["settings"].enabled = False
    assert upload(env).status_code == 503
    assert env["client"].get("/api/v1/profile/avatars").status_code == 200


def test_only_avatar_upload_gets_larger_body_limit_and_file_limit_still_applies(avatar_api):
    env = avatar_api
    large_jpeg = picture("JPEG") + b"\0" * 300_000
    assert upload(env, data=large_jpeg).status_code == 200
    assert upload(env, data=b"x" * (MAX_UPLOAD_BYTES + 1)).status_code == 413
    too_large = env["client"].post(BASE + "/upload", content=b"x" * (MAX_REQUEST_BYTES + 1))
    assert too_large.status_code == 413
    assert too_large.json()["details"]["max_bytes"] == MAX_REQUEST_BYTES
    core = env["client"].patch(BASE, content=b"x" * 300_000)
    assert core.status_code == 413
    assert core.json()["details"]["max_bytes"] == 262144


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_image_processing_strips_metadata_and_uses_oriented_crop(format):
    image = Image.new("RGB", (800, 600), "red")
    image.paste("blue", (400, 0, 800, 600))
    exif = Image.Exif()
    exif[274] = 6  # Rotates the preview to 600 x 800.
    exif[270] = "private metadata"
    stream = io.BytesIO()
    image.save(stream, format=format, exif=exif)
    data = process_image(stream.getvalue(), AvatarCrop(x=0, y=0.5, size=0.5))
    with Image.open(io.BytesIO(data)) as decoded:
        assert decoded.format == "WEBP" and decoded.size == (512, 512)
        assert not decoded.getexif()
        assert "exif" not in decoded.info and "icc_profile" not in decoded.info
        red, _green, blue = decoded.convert("RGB").getpixel((256, 256))
        assert blue > red


@pytest.mark.parametrize("kind", ["svg", "corrupt", "gif", "animated", "pixels", "crop"])
def test_invalid_images_never_reach_storage(avatar_api, kind):
    env = avatar_api
    data = picture()
    crop = None
    if kind == "svg":
        data = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    elif kind == "corrupt":
        data = data[:40]
    elif kind == "gif":
        data = picture("GIF")
    elif kind == "animated":
        stream = io.BytesIO()
        Image.new("RGB", (40, 40), "red").save(
            stream,
            format="WEBP",
            save_all=True,
            append_images=[Image.new("RGB", (40, 40), "blue")],
            duration=100,
        )
        data = stream.getvalue()
    elif kind == "pixels":
        data = picture(size=(4500, 4500))
    else:
        crop = {"x": 0.9, "y": 0.9, "size": 1}
    response = upload(env, data=data, crop=crop)
    assert response.status_code == 400, response.text
    assert not env["storage"].objects


def test_crop_rejects_non_finite_and_extra_fields(avatar_api):
    for crop in (
        {"x": float("nan"), "y": 0, "size": 1},
        {"x": 0, "y": 0, "size": 1, "url": "http://example.com"},
    ):
        assert upload(avatar_api, crop=crop).status_code == 422


def test_concurrent_uploads_with_same_revision_publish_exactly_one_avatar(avatar_api):
    env = avatar_api
    session_id = next_session(env)
    with env["app"].state.session_factory() as db:
        revision = db.get(User, env["users"]["member"]).revision
    barrier = threading.Barrier(2)
    env["storage"].on_put = lambda: barrier.wait(timeout=5)

    def attempt():
        try:
            return env["service"].upload(
                env["users"]["member"],
                session_id,
                revision,
                picture(),
                AvatarCrop(x=0, y=0, size=1),
                "concurrent-upload",
            )
        except AppError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    errors = [result for result in results if isinstance(result, AppError)]
    assert len(errors) == 1 and errors[0].code == "REVISION_CONFLICT"
    assert sorted(asset.state for asset in assets(env)) == ["active", "pending"]
    with env["app"].state.session_factory() as db:
        assert db.get(User, env["users"]["member"]).revision == revision + 1


def test_acknowledged_object_version_survives_profile_conflict(avatar_api):
    env = avatar_api
    env["storage"].version_id = "object-version-123"

    def mutate():
        with env["app"].state.session_factory.begin() as db:
            db.get(User, env["users"]["member"]).revision += 1

    env["storage"].on_put = mutate
    assert upload(env).status_code == 409
    assert assets(env)[0].version_id == "object-version-123"
    expire_assets(env)
    assert env["service"].cleanup() == 1
    assert env["storage"].deleted_versions == ["object-version-123"]


def test_request_cancellation_does_not_release_running_upload_capacity(avatar_api):
    service = avatar_api["service"]
    started = threading.Event()
    release = threading.Event()

    def slow_operation():
        started.set()
        release.wait(timeout=5)
        return "done"

    async def scenario():
        task = asyncio.create_task(service.run(slow_operation, upload=True))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # One running worker remains, so only one of the two slots is free.
        assert service.upload_slots.acquire(blocking=False)
        assert not service.upload_slots.acquire(blocking=False)
        service.upload_slots.release()
        release.set()
        for _ in range(100):
            if service.upload_slots.acquire(blocking=False):
                second = service.upload_slots.acquire(blocking=False)
                service.upload_slots.release()
                if second:
                    service.upload_slots.release()
                    return
            await asyncio.sleep(0.01)
        pytest.fail("worker did not release its slot")

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_cos_adapter_sets_private_backend_transport_and_bounds_stream_reads(monkeypatch):
    from qcloud_cos import CosConfig

    from app.custom_avatars.storage import CosAvatarStorage

    captured = {}
    stream = io.BytesIO(b"test-avatar")

    class Client:
        def __init__(self, config, retry):
            captured["config"], captured["retry"] = config, retry

        def put_object(self, **params):
            captured["put"] = params
            return {"x-cos-version-id": "version-1"}

        def get_object(self, **params):
            from types import SimpleNamespace

            return {"Body": SimpleNamespace(get_raw_stream=lambda: stream)}

        def delete_object(self, **params):
            captured["delete"] = params

    monkeypatch.setattr("qcloud_cos.CosS3Client", Client)
    storage = CosAvatarStorage(
        AvatarSettings(
            _env_file=None,
            secret_id="id",
            secret_key="secret",
            region="ap-guangzhou",
        )
    )
    assert isinstance(captured["config"], CosConfig)
    assert captured["config"]._timeout == 10 and captured["retry"] == 1
    assert storage.put("test-1234", "ap-guangzhou", "avatars/id.webp", b"data") == "version-1"
    assert captured["put"]["ContentType"] == "image/webp"
    assert captured["put"]["EnableMD5"] is True
    assert storage.get("test-1234", "ap-guangzhou", "avatars/id.webp") == b"test-avatar"
    assert stream.closed
    storage.delete("test-1234", "ap-guangzhou", "avatars/id.webp", "version-1")
    assert captured["delete"]["VersionId"] == "version-1"
    with pytest.raises(ValueError):
        storage.get("test-1234", "ap-shanghai", "avatars/id.webp")


def test_avatar_read_burst_queues_with_only_four_cloud_workers(avatar_api):
    service = avatar_api["service"]
    release = threading.Event()
    started = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum = 0

    def read():
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(active, maximum)
            if active == 4:
                started.set()
        release.wait(timeout=5)
        with lock:
            active -= 1
        return b"image"

    async def scenario():
        tasks = [asyncio.create_task(service.run(read)) for _ in range(6)]
        while not started.is_set():
            await asyncio.sleep(0.01)
        # The extra two remain queued, rather than failing with a permanent image fallback.
        assert all(not task.done() for task in tasks)
        release.set()
        assert await asyncio.gather(*tasks) == [b"image"] * 6

    try:
        asyncio.run(scenario())
        assert maximum == 4
    finally:
        release.set()


def test_invalid_optional_configuration_does_not_break_core(api, monkeypatch):
    monkeypatch.setenv("MVP_CUSTOM_AVATAR_ENABLED", "definitely-not-a-boolean")
    login(api["client"], "member")
    assert api["client"].get(BASE + "/status").json()["availability"] == "unavailable"
    assert api["client"].get("/api/v1/auth/me").status_code == 200


def test_image_processing_rejects_excessive_bytes():
    with pytest.raises(AppError) as failure:
        process_image(b"x" * (MAX_UPLOAD_BYTES + 1), AvatarCrop(x=0, y=0, size=1))
    assert failure.value.status_code == 413
