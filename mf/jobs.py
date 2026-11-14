"""Job state on disk: jobs/<id>/job.json, written only through this module."""

from __future__ import annotations

import fcntl
import json
import time
from pathlib import Path

from .config import JOBS
from .util import Refused, now_iso

_locks = {}


class Job:
    def __init__(self, data: dict):
        self.d = data

    @property
    def id(self) -> str:
        return self.d["id"]

    @property
    def stage(self) -> str:
        return self.d["stage"]

    @property
    def tracks(self) -> dict:
        return self.d["tracks"]

    @property
    def dir(self) -> Path:
        return JOBS / self.id

    def path(self, name: str) -> Path:
        return self.dir / name

    def round_dir(self, n=None) -> Path:
        return self.dir / f"round-{self.d['round'] if n is None else n}"

    def note(self, event: str) -> None:
        self.d["history"].append({"at": now_iso(), "event": event})

    def save(self) -> None:
        require_locked(self.id)
        tmp = self.path("job.json.tmp")
        tmp.write_text(json.dumps(self.d, indent=2) + "\n")
        tmp.replace(self.path("job.json"))


def lock(job_id: str) -> None:
    if job_id not in _locks:
        f = open(JOBS / job_id / ".lock", "w")
        fcntl.flock(f, fcntl.LOCK_EX)
        _locks[job_id] = f


def unlock(job_id: str) -> None:
    f = _locks.pop(job_id, None)
    if f:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def require_locked(job_id: str) -> None:
    if job_id not in _locks:
        raise Refused(f"internal: {job_id} saved without its lock")


def load(job_id: str, locked: bool = True) -> Job:
    path = JOBS / job_id / "job.json"
    if not path.exists():
        raise Refused(f"no job {job_id}")
    if locked:
        lock(job_id)
    return Job(json.loads(path.read_text()))


def all_jobs(locked: bool = False) -> list:
    if not JOBS.exists():
        return []
    return [load(p.name, locked) for p in sorted(JOBS.iterdir()) if (p / "job.json").exists()]


def find(arg: str, locked: bool = True) -> Job:
    """A job by id (004-dark-mode) or by issue number (12)."""
    if arg.isdigit():
        for j in all_jobs():
            if j.d["issue"] == int(arg):
                return load(j.id, locked)
        raise Refused(f"no job for issue #{arg}")
    return load(arg, locked)


def next_number() -> int:
    if not JOBS.exists():
        return 1
    nums = [int(p.name.split("-", 1)[0]) for p in JOBS.iterdir() if p.name[:3].isdigit()]
    return max(nums, default=0) + 1


def create(job_id: str, issue: dict, round_limit: int) -> Job:
    (JOBS / job_id).mkdir(parents=True)
    lock(job_id)
    return Job({
        "id": job_id,
        "issue": issue["number"],
        "title": issue["title"],
        "url": issue["url"],
        "stage": "intake",
        "since": time.time(),
        "round": 0,
        "round_limit": round_limit,
        "intake": None,
        "reviewers": {},
        "reviews": {},
        "tracks": {},
        "started": now_iso(),
        "ended": None,
        "history": [],
    })
