from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path

from .auth import create_user
from .backup import create_backup, restore_backup, verify_backup
from .db import init_db


def main():
    parser = argparse.ArgumentParser(description="NLHUY DAU document archive administration")
    sub = parser.add_subparsers(dest="command", required=True)
    user = sub.add_parser("create-user")
    user.add_argument("username")
    user.add_argument("--role", choices=["admin", "staff"], default="staff")
    user.add_argument("--department", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("target", type=Path)
    verify = sub.add_parser("verify-backup")
    verify.add_argument("archive", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "create-user":
        init_db()
        password = getpass("Mật khẩu (ít nhất 12 ký tự): ")
        print(create_user(args.username, password, args.role, args.department))
    elif args.command == "backup":
        print(create_backup(args.target))
    elif args.command == "verify-backup":
        print(verify_backup(args.archive))
    elif args.command == "restore":
        print(restore_backup(args.archive, args.destination))


if __name__ == "__main__":
    main()
