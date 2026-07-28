from __future__ import annotations

import argparse
import getpass

from alembic.config import Config
from sqlalchemy import select

from alembic import command
from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.models import User, UserRole
from app.security import hash_password


def upgrade_database() -> None:
    command.upgrade(Config("alembic.ini"), "head")


def create_user(args: argparse.Namespace) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    password = args.password or getpass.getpass("初始密码: ")
    if len(password) < 10:
        raise SystemExit("密码至少 10 位")
    with factory.begin() as db:
        login_name = args.login_name.strip().casefold()
        if db.scalar(select(User.id).where(User.login_name == login_name)):
            raise SystemExit("登录名已经存在")
        db.add(
            User(
                login_name=login_name,
                display_name=args.display_name.strip(),
                password_hash=hash_password(password),
                role=args.role,
                must_change_password=not args.no_force_change,
            )
        )
    engine.dispose()
    print(f"已创建用户 {args.login_name}（{args.role}）")


def main() -> None:
    parser = argparse.ArgumentParser(description="团队项目管理 MVP 管理命令")
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    subparsers.add_parser("upgrade-db", help="升级数据库到最新版本")
    user_parser = subparsers.add_parser("create-user", help="创建本地账号")
    user_parser.add_argument("login_name")
    user_parser.add_argument("display_name")
    user_parser.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        default=UserRole.MEMBER.value,
    )
    user_parser.add_argument("--password")
    user_parser.add_argument("--no-force-change", action="store_true")

    args = parser.parse_args()
    if args.command_name == "upgrade-db":
        upgrade_database()
    elif args.command_name == "create-user":
        create_user(args)


if __name__ == "__main__":
    main()
