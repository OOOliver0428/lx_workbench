from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.deployment_config import sync_config, validate_config


def test_merge_preserves_secrets_and_is_idempotent(tmp_path: Path):
    env = tmp_path / "app.env"
    original = "MVP_LLM_CONFIG_SECRET=existing-secret\nMVP_CUSTOM_AVATAR_ENABLED=false\n"
    env.write_text(original)
    template = Path(__file__).resolve().parents[1] / "deploy/ubuntu/app.env.example"
    assert sync_config(env, template) > 0
    assert "MVP_LLM_CONFIG_SECRET=existing-secret" in env.read_text()
    assert "MVP_PHONE_VERIFICATION_ENABLED=false" in env.read_text()
    assert list(tmp_path.glob("app.env.before-*"))[0].read_text() == original
    result = env.read_bytes()
    assert sync_config(env, template) == 0
    assert env.read_bytes() == result
    assert len(list(tmp_path.glob("app.env.before-*"))) == 1


def test_invalid_enabled_module_leaves_file_unchanged(tmp_path: Path):
    env = tmp_path / "app.env"
    env.write_text("MVP_PHONE_VERIFICATION_ENABLED=true\n")
    template = tmp_path / "template"
    template.write_text("MVP_PHONE_LOOKUP_KEY=\n")
    original = env.read_bytes()
    with pytest.raises(ValueError, match="手机号"):
        sync_config(env, template)
    assert env.read_bytes() == original
    assert not list(tmp_path.glob("app.env.before-*"))
    assert not list(tmp_path.glob(".app-env-*"))


def test_invalid_avatar_config_reports_no_credentials(tmp_path: Path):
    env = tmp_path / "app.env"
    env.write_text("MVP_CUSTOM_AVATAR_ENABLED=true\nMVP_AVATAR_COS_SECRET_KEY=private-value\n")
    with pytest.raises(ValueError, match="头像") as error:
        validate_config(env)
    assert "private-value" not in str(error.value)


def test_duplicate_keys_are_not_silently_merged(tmp_path: Path):
    env = tmp_path / "app.env"
    env.write_text("MVP_PHONE_VERIFICATION_ENABLED=false\nMVP_PHONE_VERIFICATION_ENABLED=true\n")
    with pytest.raises(ValueError, match="重复"):
        sync_config(env, env)
    with pytest.raises(ValueError, match="重复"):
        validate_config(env)


def test_missing_config_is_not_reported_as_disabled(tmp_path: Path):
    with pytest.raises(ValueError, match="现有"):
        validate_config(tmp_path / "missing.env")


def test_production_template_covers_development_keys_without_credentials():
    root = Path(__file__).resolve().parents[1]
    development = dotenv_values(root / ".env.example", interpolate=False)
    production = dotenv_values(root / "deploy/ubuntu/app.env.example", interpolate=False)
    assert production.keys() == development.keys()
    assert production["MVP_ENVIRONMENT"] == "production"
    assert production["MVP_PHONE_VERIFICATION_ENABLED"] == "false"
    assert production["MVP_CUSTOM_AVATAR_ENABLED"] == "false"
    for key in (
        "MVP_PHONE_LOOKUP_KEY", "MVP_ALIYUN_ACCESS_KEY_SECRET",
        "MVP_AVATAR_COS_SECRET_KEY", "MVP_LLM_CONFIG_SECRET",
    ):
        assert production[key] == ""
