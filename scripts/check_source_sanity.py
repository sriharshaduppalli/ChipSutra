#!/usr/bin/env python3
"""Fail when editor line-number prefixes ("    10|import x") leak into sources.

An agent/editor round-trip once wrote rendered line numbers back into files,
which broke imports at runtime. Cheap to check, expensive to debug.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = re.compile(r"^[ \t]*\d+\|")
SUFFIXES = {".py", ".jsx", ".js", ".sv", ".v", ".sh", ".yml", ".yaml"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "build", "dist", ".venv", "venv"}


def main() -> int:
    bad: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = [i + 1 for i, line in enumerate(text.split("\n")) if PREFIX.match(line)]
        if hits:
            bad.append(f"{path.relative_to(ROOT)}: lines {hits[:10]}")

    if bad:
        print("Line-number prefixes found in source files:")
        for entry in bad:
            print(f"  {entry}")
        return 1
    print("Source sanity OK — no line-number prefixes found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
