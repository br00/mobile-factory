"""The factory's rules, with no I/O: legal moves, file headers, routing.

Everything here is pure so it can be unit tested without git or GitHub.
"""

from __future__ import annotations

import re

from .util import Refused, require

# ---- Job and track stages ---------------------------------------------------

JOB_MOVES = {
    "intake": {"needs-info", "rejected", "spec"},
    "needs-info": {"intake", "rejected"},
    "spec": {"build"},
    "build": {"review", "needs-human"},
    "review": {"build", "approve", "needs-human"},
    "approve": {"merging", "needs-human"},
    "merging": {"merged", "needs-human"},
    "needs-human": {"build", "merging", "rejected"},
}
DONE = frozenset({"merged", "rejected"})
PARKED = frozenset({"needs-info", "needs-human"})

# A track is one platform's lane inside a job.
TRACK_MOVES = {
    "waiting": {"build"},
    "build": {"gate", "blocked"},
    "gate": {"passed", "build", "blocked"},
    "passed": {"build", "merged"},
    "blocked": {"build"},
    "merged": set(),
}
ACTIVE_TRACK = frozenset({"build", "gate"})

RISKS = ("low", "medium", "high")
SURFACES = ("ui", "security", "store", "native")
DECISIONS = ("ACCEPT", "NEEDS-INFO", "REJECT")
VERDICTS = ("PASS", "CHANGES")
ALL_WORDS = ("both", "all")


def check_move(table: dict, what: str, old: str, new: str) -> None:
    if new == "merged" and table is JOB_MOVES and old not in DONE:
        return  # a job can end as merged from anywhere once its PRs are merged
    require(new in table.get(old, ()), f"{what}: {old} -> {new} is not a legal move")


# ---- Agent files ------------------------------------------------------------


def header(text: str) -> dict:
    """`KEY: value` lines at the top of a file, up to the first blank line."""
    fields = {}
    for line in text.splitlines():
        if not line.strip():
            break
        key, sep, value = line.partition(":")
        if not sep or " " in key.strip():
            break
        fields[key.strip().upper()] = value.strip()
    return fields


def body(text: str) -> str:
    """Everything after the header block."""
    parts = text.split("\n\n", 1)
    return parts[1].strip() if len(parts) == 2 else ""


def section(text: str, heading: str):
    m = re.search(rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def word_list(value) -> list:
    items = [v.strip().lower() for v in (value or "").split(",")]
    return [v for v in items if v and v != "none"]


def targets_in(value, known: list, what: str) -> list:
    items = word_list(value)
    if any(i in ALL_WORDS for i in items):
        return list(known)
    bad = [i for i in items if i not in known]
    require(not bad, f"{what} names unknown targets: {', '.join(bad)} (known: {', '.join(known)})")
    return [k for k in known if k in items]


def parse_intake(text: str, known_targets: list) -> dict:
    h = header(text)
    decision = h.get("DECISION", "").upper()
    require(decision in DECISIONS,
            f"intake.md DECISION must be one of {', '.join(DECISIONS)}, not {decision or 'missing'!r}")
    risk = h.get("RISK", "").lower()
    require(risk in RISKS, f"intake.md RISK must be one of {', '.join(RISKS)}, not {risk or 'missing'!r}")
    surfaces = word_list(h.get("SURFACES"))
    bad = [s for s in surfaces if s not in SURFACES]
    require(not bad, f"intake.md SURFACES has unknown values: {', '.join(bad)} (known: {', '.join(SURFACES)})")
    platforms = targets_in(h.get("PLATFORMS"), known_targets, "intake.md PLATFORMS")
    if decision == "ACCEPT":
        require(platforms, "an ACCEPT intake must name PLATFORMS")
    return {
        "decision": decision,
        "risk": risk,
        "surfaces": surfaces,
        "platforms": platforms,
        "rescoped": h.get("RESCOPED", "no").lower() == "yes",
    }


def route(intake: dict, routing: dict) -> dict:
    """Reviewer name -> model, from intake's ratings and config.json routing."""
    reviewers = {}
    for p in intake["platforms"]:
        reviewers[f"code-{p}"] = routing["code"][intake["risk"]]
    if len(intake["platforms"]) > 1 and routing.get("parity"):
        reviewers["parity"] = routing["parity"]
    for s in intake["surfaces"]:
        reviewers.update(routing.get("surfaces", {}).get(s, {}))
    return reviewers


def parse_review(text: str, platforms: list):
    h = header(text)
    verdict = h.get("VERDICT", "").upper()
    require(verdict in VERDICTS, f"VERDICT must be PASS or CHANGES, not {verdict or 'missing'!r}")
    targets = targets_in(h.get("TARGETS"), platforms, "TARGETS")
    if verdict == "CHANGES":
        require(targets, "a CHANGES review must name the TARGETS that have to change")
    return verdict, targets


def rebuild_targets(reviews: dict) -> list:
    """Targets that must build again: the union of TARGETS over CHANGES reviews."""
    out = []
    for verdict, targets in reviews.values():
        if verdict == "CHANGES":
            out += [t for t in targets if t not in out]
    return out


def settle(track_stages: dict) -> str:
    """What the job does once a track changes: keep building, review, or ask a human."""
    stages = set(track_stages.values())
    if stages & ACTIVE_TRACK:
        return "build"
    if "blocked" in stages:
        return "needs-human"
    require(stages <= {"passed"}, f"unexpected track stages {sorted(stages)}")
    return "review"


def slug(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())[:5]
    return "-".join(words) or "issue"
