"""Fail closed on common credential forms in tracked text files.

This is a deliberately small offline gate for local development. It never
prints a suspected secret value. CI/production should additionally run a
maintained scanner such as Gitleaks with its updated ruleset.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_SUFFIXES = {".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".woff", ".woff2"}
ASSIGNMENT_SUFFIXES = {".env", ".ini", ".cfg", ".toml", ".yaml", ".yml", ".json"}
ASSIGNMENT = re.compile(
    r"(?i)\b(?:django_)?(?:secret|password|passwd|token|api[_-]?key|access[_-]?key|authorization|credential)"
    r"\b\s*[:=]\s*(['\"]?)([^\s,'\"]+)"
)
TOKEN_PATTERNS = {
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
SAFE_MARKERS = ("change-me", "example", "test", "redacted", "not-a-real", "unsafe-development-only")


def tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> int:
    findings: list[str] = []
    for path in tracked_paths():
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for name, pattern in TOKEN_PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{path.relative_to(ROOT)}:{line_number}: {name}")
            if path.suffix.lower() in ASSIGNMENT_SUFFIXES or path.name.startswith(".env"):
                for match in ASSIGNMENT.finditer(line):
                    value = match.group(2).lower()
                    if value and not any(marker in value for marker in SAFE_MARKERS):
                        findings.append(f"{path.relative_to(ROOT)}:{line_number}: credential_assignment")
    if findings:
        print("Potential credentials found (values intentionally withheld):")
        print("\n".join(findings))
        return 1
    print("No common credential forms found in tracked text files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
