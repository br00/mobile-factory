"""The GitHub calls the factory makes, all through the `gh` CLI."""

from __future__ import annotations

import json

from .config import MARKER
from .util import run


def gh(*args, check=True) -> str:
    return run(["gh", *args], check=check).stdout


def gh_json(*args):
    return json.loads(gh(*args))


_login = None


def login() -> str:
    """The GitHub account running the factory: its comments are trusted."""
    global _login
    if _login is None:
        _login = gh("api", "user", "--jq", ".login").strip()
    return _login


def issue(repo: str, number) -> dict:
    return gh_json("issue", "view", number, "-R", repo, "--json",
                   "number,title,body,author,labels,state,url,comments")


def labeled_issues(repo: str, label: str) -> list:
    return gh_json("issue", "list", "-R", repo, "--label", label, "--state", "open",
                   "--limit", "200", "--json", "number,title")


def comment(repo: str, number, text: str, marked: bool = True) -> None:
    gh("issue", "comment", number, "-R", repo, "--body", (MARKER + "\n" if marked else "") + text)


def add_label(repo: str, number, name: str) -> None:
    gh("issue", "edit", number, "-R", repo, "--add-label", name)


def remove_label(repo: str, number, name: str) -> None:
    gh("issue", "edit", number, "-R", repo, "--remove-label", name, check=False)


def close_issue(repo: str, number, text: str) -> None:
    gh("issue", "close", number, "-R", repo, "--comment", MARKER + "\n" + text)


def open_prs(repo: str, branch: str) -> list:
    return gh_json("pr", "list", "-R", repo, "--head", branch, "--state", "open",
                   "--json", "number,url")


def pr(repo: str, number) -> dict:
    return gh_json("pr", "view", number, "-R", repo, "--json", "number,url,state,isDraft")


def mark_ready(repo: str, number) -> None:
    if pr(repo, number)["isDraft"]:
        gh("pr", "ready", number, "-R", repo)


def merge_pr(repo: str, number, method: str) -> None:
    gh("pr", "merge", number, "-R", repo, f"--{method}")


def close_pr(repo: str, number) -> None:
    gh("pr", "close", number, "-R", repo, "--delete-branch", check=False)
