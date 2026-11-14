from __future__ import annotations

import json
import os
from pathlib import Path

from .util import Refused

# ROOT holds the factory's code. HOME holds its config and state; it is ROOT
# unless MF_HOME says otherwise (the test suite uses that).
ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("MF_HOME") or ROOT).resolve()
CONFIG_PATH = HOME / "mf.config.json"
EXAMPLE_PATH = ROOT / "mf.config.example.json"
JOBS = HOME / "jobs"
WORKTREES = HOME / ".worktrees"
CACHE = HOME / ".cache"

# Every comment the factory posts starts with this, so it can tell its own
# comments from people's.
MARKER = "<!-- mobile-factory -->"

REQUIRED = ("issues_repo", "concurrency", "max_rounds", "max_gate_attempts",
            "merge_method", "labels", "targets", "routing")
TARGET_REQUIRED = ("repo", "path", "base", "checks")


def load(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise Refused("no mf.config.json yet: run `bin/mf init` (see README.md)")
    cfg = json.loads(path.read_text())
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise Refused(f"mf.config.json is missing {', '.join(missing)}")
    if not cfg["targets"]:
        raise Refused("mf.config.json has no targets")
    for name, t in cfg["targets"].items():
        gaps = [k for k in TARGET_REQUIRED if k not in t]
        if gaps:
            raise Refused(f"mf.config.json targets.{name} is missing {', '.join(gaps)}")
    for risk in ("low", "medium", "high"):
        if risk not in cfg["routing"].get("code", {}):
            raise Refused(f"mf.config.json routing.code has no model for risk {risk!r}")
    if cfg["merge_method"] not in ("merge", "squash", "rebase"):
        raise Refused("mf.config.json merge_method must be merge, squash or rebase")


def target_path(cfg: dict, name: str) -> Path:
    """The local clone of a target's app repo."""
    p = Path(cfg["targets"][name]["path"]).expanduser()
    return p if p.is_absolute() else (HOME / p).resolve()


def checks_script(target_cfg: dict) -> Path:
    p = Path(target_cfg["checks"])
    return p if p.is_absolute() else HOME / p
