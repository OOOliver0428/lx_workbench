from __future__ import annotations

from typing import TypedDict


class AvatarOption(TypedDict):
    id: str
    label: str
    style: str
    style_label: str
    character: int
    url: str


AVATAR_STYLES = (
    ("flat", "极简扁平"),
    ("clay-soft", "柔和黏土"),
    ("pixel-soft", "简约像素"),
    ("paper", "纸艺剪纸"),
    ("line", "手绘涂鸦"),
    ("pixel", "深色像素"),
    ("clay", "立体黏土"),
)

AVATAR_OPTIONS: tuple[AvatarOption, ...] = tuple(
    {
        "id": f"{style}-{character:02d}",
        "label": f"形象 {character:02d} · {style_label}",
        "style": style,
        "style_label": style_label,
        "character": character,
        "url": f"/avatars/{style}-{character:02d}.webp",
    }
    for style, style_label in AVATAR_STYLES
    for character in range(1, 9)
)

AVATAR_KEYS = frozenset(option["id"] for option in AVATAR_OPTIONS)
