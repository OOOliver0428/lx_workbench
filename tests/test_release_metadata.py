from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_are_synchronized() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (ROOT / "frontend/package-lock.json").read_text(encoding="utf-8")
    )

    version = pyproject["project"]["version"]
    assert package["version"] == version
    assert package_lock["version"] == version
    assert package_lock["packages"][""]["version"] == version

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{version}] - " in changelog
    assert (ROOT / "app" / "__init__.py").read_text(encoding="utf-8").find(
        f'__version__ = "{version}"'
    ) >= 0
    assert f'version="{version}"' in (ROOT / "app" / "main.py").read_text(
        encoding="utf-8"
    )


def test_changelog_keeps_an_unreleased_section() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog
    for category in ("Added", "Changed", "Fixed", "Security", "Operations"):
        assert f"### {category}" in changelog
