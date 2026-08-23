#!/usr/bin/env python3
"""Fail the build if anything resembling a real device token is committed.

A miIO token is 16 bytes written as 32 hexadecimal characters, and it is a complete
credential: whoever holds it controls the device. Committing one means the device has to
be reset, and rewriting history is not sufficient because the value may already have been
fetched.

This looks for 32-character hex runs and allows only the placeholders the project
documents:

* a single character repeated, such as ``0`` x 32 or ``a`` x 32;
* the obviously sequential ``0123456789abcdef0123456789abcdef``.

Anything else is reported and the build fails. Run it locally the same way CI does:

    python .github/scripts/check_tokens.py
"""

from __future__ import annotations

import re
import subprocess
import sys

TOKEN_RE = re.compile(r"\b[0-9a-f]{32}\b")

#: Placeholders permitted in tracked files. Each is obviously synthetic.
ALLOWED = {
    # Sequential, used in documentation examples.
    "0123456789abcdef0123456789abcdef",
    # Ascending byte pattern, used as the fixture token in tests/test_transport.py.
    # A distinctive value proves the parser reads the right offsets, which a run of a
    # single character would not.
    "00112233445566778899aabbccddeeff",
}

SUFFIXES = (".py", ".md", ".json", ".toml", ".yml", ".yaml", ".sh", ".txt", ".plist")


def is_placeholder(value: str) -> bool:
    """Report whether the value is one of the documented, obviously synthetic placeholders."""
    return value in ALLOWED or len(set(value)) == 1


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if f.endswith(SUFFIXES)]


def main() -> int:
    findings: list[tuple[str, int, str]] = []

    for path in tracked_files():
        # This script necessarily contains the placeholder patterns it allows.
        if path == ".github/scripts/check_tokens.py":
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in TOKEN_RE.findall(line.lower()):
                if not is_placeholder(match):
                    findings.append((path, lineno, match))

    if findings:
        for path, lineno, value in findings:
            masked = f"{value[:4]}...{value[-4:]}"
            print(f"::error file={path},line={lineno}::"
                  f"Possible device token ({masked}). If this is real, remove it and "
                  f"reset the device to regenerate it. If it is a placeholder, use a "
                  f"repeated character such as '0' * 32.")
        print(f"\n{len(findings)} candidate token(s) found.", file=sys.stderr)
        return 1

    print(f"Checked {len(tracked_files())} tracked files. No candidate tokens found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
