#!/usr/bin/env python
"""
Claude Code PreToolUse(Bash) hook for rep.tools.

Before a `git commit`/`git push` runs, it scans the STAGED files for secrets and
compiles any staged Python. If it finds a problem it BLOCKS the command (exit 2)
and tells Claude why — so a leaked key or a syntax error literally can't ship.

Exit codes: 0 = allow, 2 = block (stderr is shown to Claude).
"""
import sys
import os
import re
import json
import subprocess

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # not our shape — don't interfere

cmd = ((payload.get("tool_input") or {}).get("command") or "")
if not re.search(r"\bgit\s+(commit|push)\b", cmd):
    sys.exit(0)  # only guard commits/pushes

# Patterns for real secrets (NOT broad enough to flag normal code).
SECRET_PATTERNS = [
    (r"apify_api_[A-Za-z0-9]{20,}", "Apify token"),
    (r"\brnd_[A-Za-z0-9]{20,}", "Render API key"),
    (r"\bre_[A-Za-z0-9]{16,}", "Resend API key"),
    (r"\bsk-[A-Za-z0-9]{20,}", "OpenAI-style key"),
    (r"\bsk-ant-[A-Za-z0-9-]{20,}", "Anthropic key"),
    (r"postgres(?:ql)?://[^\s:]+:[^\s@]+@", "Postgres URL with password"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
]

def staged_files():
    try:
        out = subprocess.check_output(["git", "diff", "--cached", "--name-only"],
                                      text=True, stderr=subprocess.DEVNULL)
        return [f for f in out.splitlines() if f.strip()]
    except Exception:
        return []

issues = []
for f in staged_files():
    if not os.path.isfile(f):
        continue
    try:
        content = open(f, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    for pat, label in SECRET_PATTERNS:
        if re.search(pat, content):
            issues.append(f"SECRET ({label}) in staged file: {f} — unstage it / move to env or a gitignored file")
    if f.endswith(".py"):
        r = subprocess.run([sys.executable, "-m", "py_compile", f],
                           capture_output=True, text=True)
        if r.returncode != 0:
            issues.append(f"{f} fails py_compile:\n{(r.stderr or '').strip()[:300]}")

if issues:
    sys.stderr.write("Pre-commit guard BLOCKED this command:\n- " + "\n- ".join(issues) + "\n")
    sys.exit(2)

sys.exit(0)
