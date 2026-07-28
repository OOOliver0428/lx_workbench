import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.dependencies import get_current_user, get_db, require_admin
from app.domain import DIRECT_LEADER_ROLES, can_be_direct_leader
from app.errors import AppError, ConflictError, NotFoundError
from app.models import User, UserRole, utc_now
from app.schemas import UserCreate, UserLeaderUpdate, UserOut, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


def _generate_login_name(db: Session) -> str:
    for _attempt in range(20):
        login_name = f"u{secrets.randbelow(100_000_000):08d}"
        if not db.scalar(select(User.id).where(User.login_name == login_name)):
            return login_name
    raise AppError(
        "LOGIN_NAME_GENERATION_FAILED",
        "暂时无法生成登录名，请重试",
        status_code=503,
    )


def _get_assignable_leader(db: Session, leader_id: str) -> User:
    leader = db.get(User, leader_id)
    if not leader or not can_be_direct_leader(leader):
        raise AppError(
            "DIRECT_LEADER_INVALID",
            "直属 Leader 必须是有效的团队负责人或系统管理员账号",
        )
    return leader


def _ensure_no_leader_cycle(db: Session, user: User, leader: User) -> None:
    current: User | None = leader
    visited: set[str] = set()
    while current and current.id not in visited:
        if current.id == user.id:
            raise AppError("DIRECT_LEADER_CYCLE", "直属 Leader 关系不能形成管理环")
        visited.add(current.id)
        current = db.get(User, current.leader_id) if current.leader_id else None


@router.get("", response_model=list[UserOut])
def list_users(
    include_inactive: bool = False,
    _actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UserOut]:
    query = select(User)
    if not include_inactive:
        query = query.where(User.is_active.is_(True))
    users = db.scalars(query.order_by(User.display_name)).all()
    return [
        UserOut.model_validate(user) for user in users if user.role != UserRole.SUPER_ADMIN.value
    ]


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    if payload.role == UserRole.SUPER_ADMIN:
        raise AppError("SUPER_ADMIN_API_FORBIDDEN", "超级管理员只能通过服务器命令创建")
    login_name = _generate_login_name(db)
    user = User(
        login_name=login_name,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role.value,
        leader_id=None,
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        after_data={
            "loginName": user.login_name,
            "displayName": user.display_name,
            "role": user.role,
            "leaderId": None,
        },
    )
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdate,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    user = db.get(User, user_id)
    if not user or user.role == UserRole.SUPER_ADMIN.value:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在")
    if payload.revision != user.revision:
        raise ConflictError(
            "REVISION_CONFLICT",
            "用户资料已被其他管理员修改，请刷新后重试",
            {
                "expected_revision": payload.revision,
                "current_revision": user.revision,
            },
        )

    fields = payload.model_fields_set - {"revision"}
    if not fields:
        raise AppError("USER_UPDATE_EMPTY", "请至少修改一项用户资料")
    before_data = {
        "displayName": user.display_name,
        "role": user.role,
        "leaderId": user.leader_id,
        "revision": user.revision,
    }
    if "role" in fields and payload.role:
        if payload.role == UserRole.SUPER_ADMIN:
            raise AppError(
                "SUPER_ADMIN_API_FORBIDDEN",
                "超级管理员角色只能通过服务器命令管理",
            )
        if actor.id == user.id and payload.role.value != user.role:
            raise AppError(
                "SELF_ROLE_CHANGE_FORBIDDEN",
                "不能修改自己的系统角色",
            )
        if (
            user.role in DIRECT_LEADER_ROLES
            and payload.role.value not in DIRECT_LEADER_ROLES
            and db.scalar(select(User.id).where(User.leader_id == user.id).limit(1))
        ):
            raise ConflictError(
                "LEADER_HAS_DIRECT_REPORTS",
                "该团队负责人仍有直属成员，请先调整这些成员的直属 Leader",
            )
        user.role = payload.role.value
    if "display_name" in fields and payload.display_name:
        user.display_name = payload.display_name.strip()
    if "leader_id" in fields:
        if payload.leader_id:
            leader = _get_assignable_leader(db, payload.leader_id)
            _ensure_no_leader_cycle(db, user, leader)
            user.leader_id = leader.id
        else:
            user.leader_id = None

    user.revision += 1
    user.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="user.update",
        entity_type="user",
        entity_id=user.id,
        before_data=before_data,
        after_data={
            "displayName": user.display_name,
            "role": user.role,
            "leaderId": user.leader_id,
            "revision": user.revision,
        },
    )
    return UserOut.model_validate(user)


@router.patch("/{user_id}/leader", response_model=UserOut)
def update_user_leader(
    user_id: str,
    payload: UserLeaderUpdate,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    user = db.get(User, user_id)
    if not user or user.role == UserRole.SUPER_ADMIN.value:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在")
    if payload.revision != user.revision:
        raise ConflictError(
            "REVISION_CONFLICT",
            "用户资料已被其他管理员修改，请刷新后重试",
            {
                "expected_revision": payload.revision,
                "current_revision": user.revision,
            },
        )

    previous_leader_id = user.leader_id
    if payload.leader_id:
        leader = _get_assignable_leader(db, payload.leader_id)
        _ensure_no_leader_cycle(db, user, leader)
        user.leader_id = leader.id
    else:
        user.leader_id = None
    user.revision += 1
    user.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="user.leader.update",
        entity_type="user",
        entity_id=user.id,
        before_data={"leaderId": previous_leader_id},
        after_data={"leaderId": user.leader_id, "revision": user.revision},
    )
    return UserOut.model_validate(user)
