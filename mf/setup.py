"""`mf init` and `mf doctor`: getting a factory pointed at your apps."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import checks, gh
from . import config as C
from .util import Refused, require, run

LABELS = {
    "queue": ("0E8A16", "mobile-factory: build this"),
    "needs_info": ("FBCA04", "mobile-factory: waiting for the author"),
    "needs_human": ("D93F0B", "mobile-factory: waiting for the operator"),
    "suggested": ("C5DEF5", "mobile-factory: suggested by the survey; add the queue label to build it"),
}


def parse_target(spec: str, flag: str):
    repo, sep, path = spec.partition("=")
    require(sep and re.fullmatch(r"[\w.-]+/[\w.-]+", repo) and path,
            f"{flag} wants OWNER/REPO=PATH, e.g. {flag} acme/app-ios=../app-ios")
    return repo, path


def init(a) -> None:
    require(not C.CONFIG_PATH.exists() or a.force, "mf.config.json exists; pass --force to overwrite it")
    require(re.fullmatch(r"[\w.-]+/[\w.-]+", a.issues), "--issues wants OWNER/REPO")
    require(a.ios or a.android, "name at least one app: --ios and/or --android")
    cfg = json.loads(C.EXAMPLE_PATH.read_text())
    cfg.pop("//", None)
    cfg["issues_repo"] = a.issues
    for name, spec in (("ios", a.ios), ("android", a.android)):
        if spec is None:
            cfg["targets"].pop(name)
            cfg["merge_order"] = [t for t in cfg["merge_order"] if t != name]
            continue
        repo, path = parse_target(spec, f"--{name}")
        cfg["targets"][name]["repo"] = repo
        cfg["targets"][name]["path"] = path
    C.validate(cfg)
    C.CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"wrote {C.CONFIG_PATH}")
    for key, (color, desc) in LABELS.items():
        name = cfg["labels"].get(key)
        if not name:
            continue
        gh.gh("label", "create", name, "-R", a.issues, "--force", "--color", color, "--description", desc)
        print(f"label {name} ready in {a.issues}")
    print("\nnext:")
    if "ios" in cfg["targets"]:
        print("  - set targets.ios.env (MF_SCHEME, MF_PROJECT or MF_WORKSPACE, MF_DESTINATION)")
    if "android" in cfg["targets"]:
        print("  - set targets.android.env.MF_GRADLE_TASKS to your lint + unit test + build tasks")
    print("  - run bin/mf doctor --checks")
    print("  - in Claude Code, run /mf survey so the factory learns both apps first")


class Report:
    def __init__(self):
        self.failed = False

    def ok(self, msg):
        print(f"  ok    {msg}")

    def warn(self, msg):
        print(f"  warn  {msg}")

    def fail(self, msg):
        print(f"  FAIL  {msg}")
        self.failed = True

    def tool(self, name, needed=True, why=""):
        if shutil.which(name):
            self.ok(f"{name} found")
        elif needed:
            self.fail(f"{name} not found{': ' + why if why else ''}")
        else:
            self.warn(f"{name} not found{': ' + why if why else ''}")


def iphones() -> list:
    """Available iPhone simulators, newest runtime first: [(version tuple, name, udid)]."""
    res = run(["xcrun", "simctl", "list", "devices", "available", "-j"], check=False)
    if res.returncode != 0:
        return []
    out = []
    for runtime, devices in json.loads(res.stdout).get("devices", {}).items():
        m = re.search(r"iOS-(\d+)-(\d+)", runtime)
        if not m:
            continue
        version = (int(m.group(1)), int(m.group(2)))
        out += [(version, d["name"], d["udid"]) for d in devices
                if d.get("isAvailable", True) and d["name"].startswith("iPhone")]
    return sorted(out, key=lambda x: x[0], reverse=True)


def default_destination() -> str:
    phones = iphones()
    require(phones, "no iPhone simulator is available: add one in Xcode > Window > Devices and Simulators")
    return f"platform=iOS Simulator,id={phones[0][2]}"


def destination_exists(dest: str) -> bool:
    phones = iphones()
    m = re.search(r"id=([0-9A-F-]{36})", dest)
    if m:
        return any(p[2] == m.group(1) for p in phones)
    m = re.search(r"name=([^,]+)", dest)
    return bool(m) and any(p[1] == m.group(1).strip() for p in phones)


def java_for(env: dict):
    """The java a target's builds will use, and whether it runs: (path, ok, detail)."""
    home = env.get("JAVA_HOME") or os.environ.get("JAVA_HOME")
    java = str(Path(home) / "bin" / "java") if home else shutil.which("java")
    if not java:
        return None, False, "no java found"
    res = run([java, "-version"], check=False)
    first = (res.stderr or res.stdout).strip().splitlines()[:1]
    return java, res.returncode == 0, first[0] if first else ""


def android_sdk(env: dict, clone: Path):
    for value in (env.get("ANDROID_HOME"), os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                  str(Path.home() / "Library" / "Android" / "sdk")):
        if value and (Path(value).expanduser() / "platforms").is_dir():
            return Path(value).expanduser()
    return None


def same_repo(url: str, repo: str) -> bool:
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url.strip())
    return bool(m) and m.group(1).lower() == repo.lower()


def doctor(run_checks: bool) -> int:
    r = Report()
    print("tools")
    if sys.version_info >= (3, 9):
        r.ok(f"python {sys.version.split()[0]}")
    else:
        r.fail("python 3.9 or later is required")
    r.tool("git")
    r.tool("gh", why="install the GitHub CLI and run `gh auth login`")
    r.tool("claude", needed=False, why="Claude Code runs the /mf skill")
    r.tool("maestro", needed=False, why="needed for the full gate (flow.yaml), not for the fast gate")
    if shutil.which("gh") and run(["gh", "auth", "status"], check=False).returncode != 0:
        r.fail("gh isn't signed in: run `gh auth login`")

    print("config")
    try:
        cfg = C.load()
        r.ok(f"{C.CONFIG_PATH.name} is valid ({', '.join(cfg['targets'])})")
    except Refused as e:
        r.fail(str(e))
        return 1

    print(f"issues repo {cfg['issues_repo']}")
    try:
        names = {l["name"] for l in gh.gh_json("label", "list", "-R", cfg["issues_repo"],
                                               "--limit", "200", "--json", "name")}
        r.ok("reachable")
        for key, name in cfg["labels"].items():
            (r.ok if name in names else r.fail)(f"label {name}" + ("" if name in names else " missing: run bin/mf init"))
    except Refused as e:
        r.fail(f"can't read it: {e}")

    for t, tc in cfg["targets"].items():
        print(f"target {t} ({tc['repo']})")
        clone = C.target_path(cfg, t)
        if not (clone / ".git").exists():
            r.fail(f"{clone} isn't a git clone: clone {tc['repo']} there or fix targets.{t}.path")
            continue
        r.ok(f"clone at {clone}")
        url = run(["git", "remote", "get-url", "origin"], cwd=clone, check=False).stdout
        if same_repo(url, tc["repo"]):
            r.ok("origin matches")
        else:
            r.fail(f"origin is {url.strip() or 'missing'}, expected {tc['repo']}")
        heads = run(["git", "ls-remote", "--heads", "origin", tc["base"]], cwd=clone, check=False).stdout
        (r.ok if heads.strip() else r.fail)(f"base branch {tc['base']} " + ("exists" if heads.strip() else "not found on origin"))
        script = C.checks_script(tc)
        (r.ok if script.exists() else r.fail)(f"checks script {tc['checks']}")
        if t == "ios":
            r.tool("xcodebuild", why="install Xcode")
            r.tool("swiftlint", needed=False, why="lint runs only when the app has .swiftlint.yml")
            if not tc.get("env", {}).get("MF_SCHEME"):
                r.fail("targets.ios.env.MF_SCHEME isn't set")
            dest = tc.get("env", {}).get("MF_DESTINATION", "")
            if not dest:
                phones = iphones()
                if phones:
                    r.ok(f"simulator: automatic ({phones[0][1]}, iOS {phones[0][0][0]}.{phones[0][0][1]})")
                else:
                    r.fail("no iPhone simulator is available: add one in Xcode > Window > Devices and Simulators")
            elif destination_exists(dest):
                r.ok(f"simulator {dest}")
            else:
                names = sorted({p[1] for p in iphones()})
                r.fail(f"simulator {dest!r} doesn't exist here. Leave MF_DESTINATION empty to pick one "
                       f"automatically, or use one of: {', '.join(names) or 'none installed'}")
            if (clone / "project.yml").exists() or (clone / "Project.swift").exists():
                r.ok("generated Xcode project (XcodeGen/Tuist): agents edit the spec, not project.pbxproj")
            elif any("PBXFileSystemSynchronizedRootGroup" in p.read_text(errors="ignore")
                     for p in clone.glob("*.xcodeproj/project.pbxproj")):
                r.ok("Xcode synchronized folders: new files need no project.pbxproj edits")
            else:
                r.warn("classic Xcode groups: every new file means a project.pbxproj edit. "
                       "Consider converting to synchronized folders (Xcode 16) or XcodeGen/Tuist.")
        if t == "android":
            env = tc.get("env", {})
            java, ok, detail = java_for(env)
            if ok:
                r.ok(f"java runs: {detail} ({java})")
            else:
                r.fail(f"java doesn't run ({java or 'missing'}: {detail}). Set targets.android.env.JAVA_HOME "
                       "to a JDK 17+ built for this Mac (`/usr/libexec/java_home -V` lists them; Android "
                       "Studio ships one in Android Studio.app/Contents/jbr/Contents/Home)")
            sdk = android_sdk(env, clone)
            if sdk:
                r.ok(f"Android SDK at {sdk}")
            else:
                r.fail("no Android SDK found: install one with Android Studio, or set "
                       "targets.android.env.ANDROID_HOME")
            (r.ok if (clone / "gradlew").exists() else r.fail)("gradlew in the clone")
            r.tool("adb", needed=False, why="needed for the full gate on an emulator")
        profile = C.PROFILES / f"{t}.md"
        if profile.exists():
            r.ok(f"house rules in profiles/{t}.md")
        else:
            r.warn(f"no profiles/{t}.md yet: run /mf survey so agents learn this app's conventions")
        if run_checks:
            run_base_checks(cfg, t, tc, clone, r)
    print()
    print("doctor: " + ("problems found" if r.failed else "all good"))
    return 1 if r.failed else 0


def run_base_checks(cfg, t, tc, clone, r) -> None:
    """Run the target's checks on a throwaway worktree of its base branch."""
    wt = C.CACHE / "doctor" / t / "worktree"
    if wt.exists():
        run(["git", "worktree", "remove", "--force", str(wt)], cwd=clone, check=False)
    wt.parent.mkdir(parents=True, exist_ok=True)
    try:
        run(["git", "fetch", "origin", tc["base"]], cwd=clone)
        run(["git", "worktree", "add", "--detach", str(wt), f"origin/{tc['base']}"], cwd=clone)
        print(f"  ...   running {tc['checks']} on origin/{tc['base']} (this can take minutes)")
        res = checks.execute(tc, t, str(wt), C.CACHE / "doctor" / t / "cache", "doctor", fresh=True)
        log = C.CACHE / "doctor" / f"{t}.log"
        log.write_text(res["log"])
        if res["ok"]:
            r.ok(f"checks pass on {tc['base']} in {res['seconds']}s")
        else:
            r.fail(f"checks fail on {tc['base']} (exit {res['code']}); the factory can't judge branches "
                   f"until they pass. Log: {log}")
    except Refused as e:
        r.fail(str(e))
    finally:
        run(["git", "worktree", "remove", "--force", str(wt)], cwd=clone, check=False)
