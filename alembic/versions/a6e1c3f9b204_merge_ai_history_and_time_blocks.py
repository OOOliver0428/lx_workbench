"""merge ai history and work record time block heads

Revision ID: a6e1c3f9b204
Revises: d1f2a3b4c5e6, f1a6b7c8d902
Create Date: 2026-08-17
"""

from collections.abc import Sequence


revision: str = "a6e1c3f9b204"
down_revision: tuple[str, str] = ("d1f2a3b4c5e6", "f1a6b7c8d902")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
