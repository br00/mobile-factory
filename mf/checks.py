"""Running a target's checks script in a worktree, and writing the gate report."""

from __future__ import annotations

import fnmatch
import os
import subprocess
import time
from pathlib import Path

from .config import CACHE, checks_script
from .util import require, run

TAIL = 60


def protected_changes(worktree: str, base: str, patterns: list) -> list:
    """Existing files matching a protected pattern that the branch modified or deleted."""
    diff = run(["git", "diff", "--name-status", f"origin/{base}...HEAD"], cwd=worktree).stdout
    hits = []
    for line in diff.splitlines():
        status, *paths = line.split("\t")
        if not paths or status.startswith("A"):
            continue
        old = paths[0]
        if any(fnmatch.fnmatch(old, p) for p in patterns):
            hits.append(f"{status[0]} {old}")
    return hits


def execute(target_cfg: dict, target: str, worktree: str, cache: Path, job_id: str = "") -> dict:
    """Run the target's checks script from the factory repo inside `worktree`."""
    script = checks_script(target_cfg)
    require(script.exists(), f"{target}: checks script {script} doesn't exist")
    cache.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({k: str(v) for k, v in target_cfg.get("env", {}).items()})
    env.update(MF_WORKTREE=str(worktree), MF_CACHE=str(cache), MF_TARGET=target, MF_JOB=job_id)
    commit = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    protected = protected_changes(worktree, target_cfg["base"], target_cfg.get("protected_paths", []))
    start = time.monotonic()
    res = subprocess.run(["bash", str(script)], cwd=worktree, env=env, capture_output=True, text=True)
    return {
        "ok": res.returncode == 0 and not protected,
        "code": res.returncode,
        "log": res.stdout + res.stderr,
        "seconds": int(time.monotonic() - start),
        "protected": protected,
        "commit": commit,
    }


def job_cache(job_id: str, target: str) -> Path:
    return CACHE / job_id / target


def summary_line(target: str, name: str, r: dict) -> str:
    extra = f", protected paths changed: {', '.join(r['protected'])}" if r["protected"] else ""
    return (f"{target} {name}: {'PASS' if r['ok'] else 'FAIL'} "
            f"(checks exit {r['code']} in {r['seconds']}s{extra})")


def write_report(round_dir: Path, name: str, target: str, r: dict, note: str = "") -> Path:
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / f"{name}.log").write_text(r["log"])
    tail = "\n".join(r["log"].rstrip().splitlines()[-TAIL:])
    outcome = "passed" if r["code"] == 0 else f"failed with exit {r['code']}"
    bullets = [
        f"Checks {outcome} in {r['seconds']}s",
        "Protected paths: " + (", ".join(r["protected"]) if r["protected"] else "none changed"),
        f"Commit {r['commit'][:9]}" + (f", {note}" if note else ""),
    ]
    report = (
        f"GATE: {'PASS' if r['ok'] else 'FAIL'}\nTARGET: {target}\nCOMMIT: {r['commit']}\n\n"
        "## Summary\n" + "\n".join(f"- {b}" for b in bullets) + "\n\n"
        "## Protected paths\n"
        + ("\n".join(f"- {p}" for p in r["protected"]) if r["protected"] else "None changed.") + "\n\n"
        f"## Output\nLast {TAIL} lines of {name}.log:\n\n```\n{tail}\n```\n"
    )
    path = round_dir / f"{name}.md"
    path.write_text(report)
    return path
