"""Minimal CLI for database initialization and health inspection."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .store import OmniIntelStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="omniintel")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Initialize or migrate a local OmniIntel database")
    init.add_argument("database", type=Path)
    check = sub.add_parser("check", help="Run SQLite integrity checks")
    check.add_argument("database", type=Path)
    args = parser.parse_args()
    if args.command == "init":
        OmniIntelStore(args.database)
        print(f"Initialized database: {args.database}")
    elif args.command == "check":
        with sqlite3.connect(args.database) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        print(f"integrity_check: {result}")
        print(f"foreign_key_violations: {len(fk)}")
        if result != "ok" or fk:
            raise SystemExit(1)
