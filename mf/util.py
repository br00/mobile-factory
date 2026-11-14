from __future__ import annotations

import subprocess
from datetime import datetime, timezone


class Refused(Exception):
    """A rule or an external command said no. The message says why."""


def require(cond, msg: str) -> None:
    if not cond:
        raise Refused(msg)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd, cwd=None, check=True, env=None, input=None) -> subprocess.CompletedProcess:
    res = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True,
                         env=env, input=input)
    if check and res.returncode != 0:
        detail = (res.stderr or res.stdout).strip()
        raise Refused(f"`{' '.join(str(c) for c in cmd)}` failed: {detail}")
    return res
