#!/usr/bin/env python3
"""团队项目管理 MVP 后端启动入口。"""

from __future__ import annotations

import argparse

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="启动团队项目管理 MVP 后端")
    parser.add_argument("--host", default=settings.server_host)
    parser.add_argument("--port", type=int, default=settings.server_port)
    parser.add_argument("--reload", action="store_true", help="仅用于本地开发")
    args = parser.parse_args()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1,
    )


if __name__ == "__main__":
    main()
