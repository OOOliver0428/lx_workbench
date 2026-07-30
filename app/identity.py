from __future__ import annotations


def normalize_user_identifier(value: str) -> str:
    """Normalize login names and display names for comparison."""

    return value.strip().casefold()
