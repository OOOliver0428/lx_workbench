"""Merge deployment defaults without replacing existing credentials or switches."""

from __future__ import annotations

import argparse
import os
import re
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

from app.custom_avatars.config import AvatarSettings
from app.phone.config import PhoneSettings
from app.phone.crypto import PhoneCrypto


def validate_config(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("配置必须是现有普通文件")
    keys = re.findall(
        r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", path.read_text(encoding="utf-8"), re.M
    )
    if len(keys) != len(set(keys)):
        raise ValueError("配置中存在重复参数，请先合并重复项")
    values = {key: value for key, value in dotenv_values(path, interpolate=False).items()}
    try:
        phone = PhoneSettings(_env_file=None, **values)
        if phone.enabled:
            PhoneCrypto(phone)
            if not phone.provider_ready():
                raise ValueError
    except Exception:
        raise ValueError("手机号配置无效：检查独立密钥、阿里云参数与频控配置") from None
    try:
        avatar = AvatarSettings(_env_file=None, **values)
        if avatar.enabled and not avatar.configured():
            raise ValueError
    except Exception:
        raise ValueError("头像配置无效：检查 COS 凭证、完整桶名、地域与前缀") from None


def sync_config(path: Path, template: Path) -> int:
    if path.is_symlink() or not path.is_file():
        raise ValueError("配置必须是现有普通文件")
    original = path.read_text(encoding="utf-8")
    keys = re.findall(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", original, re.M)
    if len(keys) != len(set(keys)):
        raise ValueError("配置中存在重复参数，请先合并重复项")
    missing = []
    for line in template.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match and match[1] not in keys:
            missing.append(line)
    if not missing:
        validate_config(path)
        return 0
    metadata = path.stat()
    descriptor, name = tempfile.mkstemp(prefix=".app-env-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(original.rstrip("\n") + "\n\n# Added deployment defaults (0.5.1)\n")
            stream.write("\n".join(missing) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        validate_config(temporary)
        # Backup before the atomic replacement, preserving the original byte content.
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(path.name + ".before-" + stamp)
        with backup.open("xb") as stream:
            os.chmod(backup, 0o600)
            stream.write(path.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        if hasattr(os, "chown"):
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
        return len(missing)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="同步部署配置缺项并校验，不输出凭证")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--template", type=Path)
    args = parser.parse_args()
    try:
        if args.template:
            count = sync_config(args.file, args.template)
            print(f"配置检查通过；补齐 {count} 项，已有值保持不变。")
        else:
            validate_config(args.file)
            print("配置检查通过（未调用云服务）。")
    except (ValueError, OSError):
        # Never surface parsing/SDK exceptions that may contain configuration values.
        raise SystemExit(
            "配置检查失败：检查文件权限、重复项及手机号/COS配置；配置未自动修正。"
        ) from None


if __name__ == "__main__":
    main()
