from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Department, User, UserRole, WeeklyReport, WeeklyRoster
from app.services.weekly_rosters import capture_current_roster, current_week

SCOPE_ALL_LED = "all_led"
SCOPE_DEPARTMENT = "department"
SCOPE_OTHER_DIRECT = "other_direct"
SCOPE_FULL = "full"
SCOPE_LEGACY_ORG = "legacy_org"

VALID_REQUEST_SCOPES = {
    SCOPE_ALL_LED,
    SCOPE_DEPARTMENT,
    SCOPE_OTHER_DIRECT,
}

MANAGED_ROLES = {
    UserRole.MEMBER.value,
    UserRole.TEAM_LEADER.value,
    UserRole.SYSTEM_ADMIN.value,
}


@dataclass(frozen=True)
class ScopeOption:
    scope_type: str
    department_id: str | None
    department_name: str | None
    member_count: int


@dataclass
class ResolvedManagementScope:
    scope_type: str
    department_id: str | None
    members: list[User] = field(default_factory=list)
    options: list[ScopeOption] = field(default_factory=list)
    led_departments: list[Department] = field(default_factory=list)
    other_direct_count: int = 0
    is_org_wide: bool = False
    includes_actor: bool = False
    roster_known: bool = True
    department_by_user: dict[str, str | None] = field(default_factory=dict)


def _led_departments(db: Session, user_id: str) -> list[Department]:
    return list(
        db.scalars(
            select(Department)
            .where(
                Department.leader_id == user_id,
                Department.deleted_at.is_(None),
                Department.is_active.is_(True),
            )
            .order_by(Department.name, Department.id)
        ).all()
    )


def _reporting_tree(db: Session, actor: User) -> list[User]:
    organization_users = list(
        db.scalars(
            select(User).where(User.role != UserRole.SUPER_ADMIN.value)
        ).all()
    )
    reports_by_leader: dict[str, list[User]] = defaultdict(list)
    for user in organization_users:
        if user.leader_id:
            reports_by_leader[user.leader_id].append(user)
    scoped: list[User] = []
    pending: deque[str] = deque([actor.id])
    visited: set[str] = set()
    while pending:
        user_id = pending.popleft()
        if user_id in visited:
            continue
        visited.add(user_id)
        for report in reports_by_leader.get(user_id, []):
            if report.id in visited:
                continue
            if report.is_active:
                scoped.append(report)
            pending.append(report.id)
    return scoped


def _department_members(db: Session, department_id: str, *, exclude_id: str | None) -> list[User]:
    rows = list(
        db.scalars(
            select(User)
            .where(
                User.primary_department_id == department_id,
                User.is_active.is_(True),
                User.role != UserRole.SUPER_ADMIN.value,
            )
            .order_by(User.display_name, User.id)
        ).all()
    )
    if exclude_id:
        rows = [user for user in rows if user.id != exclude_id]
    return [user for user in rows if user.role in MANAGED_ROLES]


def resolve_management_scope(
    db: Session,
    actor: User,
    *,
    scope_type: str | None = None,
    department_id: str | None = None,
    week_start: date | None = None,
) -> ResolvedManagementScope:
    """Resolve work-management member scope.

    - Super admin: organization-wide business users (legacy full view).
    - Ordinary members: organization-wide business users (unchanged).
    - Team leaders / system admins: department buckets over led departments,
      plus "other direct" reporting-tree members outside those departments.
      The actor is never part of managed submission metrics.
    """

    if actor.role not in {
        UserRole.TEAM_LEADER.value,
        UserRole.SYSTEM_ADMIN.value,
    }:
        users = list(
            db.scalars(
                select(User)
                .where(
                    User.is_active.is_(True),
                    User.role.in_([UserRole.MEMBER.value, UserRole.TEAM_LEADER.value]),
                )
                .order_by(User.display_name)
            ).all()
        )
        return ResolvedManagementScope(
            scope_type=SCOPE_FULL if actor.role == UserRole.SUPER_ADMIN.value else SCOPE_LEGACY_ORG,
            department_id=None,
            members=users,
            is_org_wide=True,
            includes_actor=True,
        )

    led = _led_departments(db, actor.id)
    led_ids = {department.id for department in led}
    week = week_start or current_week()
    roster = capture_current_roster(db) if week == current_week() else db.get(WeeklyRoster, week)
    if roster is not None:
        entries = {entry["user_id"]: entry for entry in roster.members}
    else:
        # No historical denominator exists: only use formally submitted snapshots.
        entries = {
            report.author_id: {
                "user_id": report.author_id,
                "department_id": report.department_id,
            }
            for report in db.scalars(
                select(WeeklyReport).where(
                    WeeklyReport.week_start == week,
                    WeeklyReport.submitted_at.is_not(None),
                    WeeklyReport.submitted_content.is_not(None),
                    (
                        WeeklyReport.department_snapshot_known.is_(True)
                        | WeeklyReport.department_id.is_not(None)
                    ),
                )
            )
        }
    period_users = list(db.scalars(select(User).where(User.id.in_(entries))).all())
    period_departments = {uid: entry.get("department_id") for uid, entry in entries.items()}
    department_buckets: dict[str, list[User]] = {
        department.id: [
            user
            for user in period_users
            if user.id != actor.id and period_departments.get(user.id) == department.id
        ]
        for department in led
    }
    tree = _reporting_tree(db, actor)
    if roster is not None and week != current_week():
        descendants = {actor.id}
        while True:
            expanded = descendants | {
                uid for uid, entry in entries.items() if entry.get("leader_id") in descendants
            }
            if expanded == descendants:
                break
            descendants = expanded
        tree = [user for user in period_users if user.id in descendants and user.id != actor.id]
    other_direct = [
        user
        for user in tree
        if user.id in entries and period_departments.get(user.id) not in led_ids
    ]
    period_fields = {"roster_known": roster is not None, "department_by_user": period_departments}

    options: list[ScopeOption] = []
    if led:
        options.append(
            ScopeOption(
                scope_type=SCOPE_ALL_LED,
                department_id=None,
                department_name=None,
                member_count=sum(len(users) for users in department_buckets.values()),
            )
        )
        for department in led:
            options.append(
                ScopeOption(
                    scope_type=SCOPE_DEPARTMENT,
                    department_id=department.id,
                    department_name=department.name,
                    member_count=len(department_buckets.get(department.id, [])),
                )
            )
    if other_direct:
        options.append(
            ScopeOption(
                scope_type=SCOPE_OTHER_DIRECT,
                department_id=None,
                department_name=None,
                member_count=len(other_direct),
            )
        )

    if not options:
        return ResolvedManagementScope(
            scope_type=SCOPE_OTHER_DIRECT,
            department_id=None,
            members=[],
            options=[],
            led_departments=led,
            other_direct_count=0,
            **period_fields,
        )

    requested = (scope_type or "").strip()
    requested_dept = (department_id or "").strip() or None

    if requested == SCOPE_DEPARTMENT and requested_dept:
        if requested_dept not in led_ids:
            return ResolvedManagementScope(
                scope_type=SCOPE_ALL_LED if led else SCOPE_OTHER_DIRECT,
                department_id=None,
                members=_members_for_bucket(
                    led,
                    department_buckets,
                    other_direct,
                    scope_type=SCOPE_ALL_LED if led else SCOPE_OTHER_DIRECT,
                ),
                options=options,
                led_departments=led,
                other_direct_count=len(other_direct),
                **period_fields,
            )
        return ResolvedManagementScope(
            scope_type=SCOPE_DEPARTMENT,
            department_id=requested_dept,
            members=department_buckets.get(requested_dept, []),
            options=options,
            led_departments=led,
            other_direct_count=len(other_direct),
            **period_fields,
        )

    if requested == SCOPE_OTHER_DIRECT and other_direct:
        return ResolvedManagementScope(
            scope_type=SCOPE_OTHER_DIRECT,
            department_id=None,
            members=other_direct,
            options=options,
            led_departments=led,
            other_direct_count=len(other_direct),
            **period_fields,
        )

    default_type = SCOPE_ALL_LED if led else SCOPE_OTHER_DIRECT
    return ResolvedManagementScope(
        scope_type=default_type,
        department_id=None,
        members=_members_for_bucket(
            led,
            department_buckets,
            other_direct,
            scope_type=default_type,
        ),
        options=options,
        led_departments=led,
        other_direct_count=len(other_direct),
        **period_fields,
    )


def _members_for_bucket(
    led: list[Department],
    department_buckets: dict[str, list[User]],
    other_direct: list[User],
    *,
    scope_type: str,
) -> list[User]:
    if scope_type == SCOPE_OTHER_DIRECT:
        return list(other_direct)
    members: list[User] = []
    seen: set[str] = set()
    for department in led:
        for user in department_buckets.get(department.id, []):
            if user.id in seen:
                continue
            seen.add(user.id)
            members.append(user)
    members.sort(key=lambda user: (user.display_name, user.id))
    return members


def normalize_scope_key(scope_type: str, department_id: str | None) -> str:
    if scope_type == SCOPE_DEPARTMENT and department_id:
        return f"{SCOPE_DEPARTMENT}:{department_id}"
    if scope_type in VALID_REQUEST_SCOPES:
        return SCOPE_ALL_LED if scope_type == SCOPE_ALL_LED else SCOPE_OTHER_DIRECT
    return SCOPE_ALL_LED
