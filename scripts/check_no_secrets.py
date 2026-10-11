"""Fail before publishing known API key formats without echoing secret values."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


PATTERNS = (
    re.compile(rb"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(rb"AQ\.[A-Za-z0-9_-]{30,}"),
)


def main() -> int:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    ).split(b"\0")
    violations = []
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path.decode("utf-8", errors="surrogateescape"))
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        content = path.read_bytes()
        if b"\0" in content[:8192]:
            continue
        for pattern in PATTERNS:
            for match in pattern.finditer(content):
                violations.append((str(path), content.count(b"\n", 0, match.start()) + 1))
    if violations:
        for path, line in violations:
            print(f"Potential API key in {path}:{line} (value hidden)")
        return 1
    print("No matching API key literals in publishable files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
