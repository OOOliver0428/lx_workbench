"""Compatibility wording for previously stored product copy and account labels."""


def public_admin_copy(value: str) -> str:
    return value.replace("超级管理员", "系统维护").replace("超管", "系统维护")
