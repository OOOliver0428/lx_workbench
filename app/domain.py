from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models import User, UserRole

PRIVILEGED_ROLES = {
    UserRole.TEAM_LEADER.value,
    UserRole.SYSTEM_ADMIN.value,
    UserRole.SUPER_ADMIN.value,
}

ADMIN_ROLES = {
    UserRole.SYSTEM_ADMIN.value,
    UserRole.SUPER_ADMIN.value,
}

DIRECT_LEADER_ROLES = {
    UserRole.TEAM_LEADER.value,
    UserRole.SYSTEM_ADMIN.value,
}


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def new_project_code() -> str:
    date_part = datetime.now(UTC).strftime("%Y%m%d")
    return f"PRJ-{date_part}-{uuid.uuid4().hex[:8].upper()}"


def new_opportunity_code() -> str:
    date_part = datetime.now(UTC).strftime("%Y%m%d")
    return f"OPP-{date_part}-{uuid.uuid4().hex[:8].upper()}"


def new_department_work_code() -> str:
    date_part = datetime.now(UTC).strftime("%Y%m%d")
    return f"DW-{date_part}-{uuid.uuid4().hex[:8].upper()}"


def is_privileged(user: User) -> bool:
    return user.role in PRIVILEGED_ROLES


def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES


def is_super_admin(user: User) -> bool:
    return user.role == UserRole.SUPER_ADMIN.value


def can_be_direct_leader(user: User) -> bool:
    return user.is_active and user.role in DIRECT_LEADER_ROLES


def jsonable_snapshot(instance: object, fields: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(instance, field)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        result[field] = value
    return result
