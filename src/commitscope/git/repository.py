from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from commitscope.config import RepoConfig
from commitscope.utils.fs import ensure_dir


@dataclass(slots=True)
class CommitRecord:
    commit_hash: str
    author: str
    author_email: str
    timestamp: datetime
    message: str
    files_changed: int
    insertions: int
    deletions: int


def repo_name_from_url(url: str) -> str:
    path = urlparse(url).path.rsplit("/", maxsplit=1)[-1]
    return path.removesuffix(".git") or "repository"


def clone_or_update_repository(config: RepoConfig) -> Path:
    checkout_root = ensure_dir(config.checkout_root)
    repo_path = checkout_root / repo_name_from_url(config.url)
    if not repo_path.exists():
        _run_git(["clone", "--branch", config.branch, "--single-branch", config.url, str(repo_path)])
    else:
        _run_git(["-C", str(repo_path), "fetch", "--all", "--tags", "--prune"])
        _run_git(["-C", str(repo_path), "checkout", config.branch])
        _run_git(["-C", str(repo_path), "pull", "--ff-only", "origin", config.branch])
    return repo_path


def select_commits(repo_path: Path, config: RepoConfig) -> list[CommitRecord]:
    from pydriller import Repository

    since = _parse_dt(config.since)
    until = _parse_dt(config.until)
    repository = Repository(
        str(repo_path),
        only_in_branch=config.branch,
        since=since,
        to=until,
        from_commit=config.from_commit,
        to_commit=config.to_commit,
    )
    commits: list[CommitRecord] = []
    for commit in repository.traverse_commits():
        commits.append(
            CommitRecord(
                commit_hash=commit.hash,
                author=commit.author.name,
                author_email=commit.author.email,
                timestamp=commit.author_date,
                message=commit.msg,
                files_changed=len(commit.modified_files),
                insertions=commit.insertions,
                deletions=commit.deletions,
            )
        )
        if len(commits) >= config.max_commits:
            break
    return commits


def checkout_commit(repo_path: Path, commit_hash: str) -> None:
    _run_git(["-C", str(repo_path), "checkout", "--force", commit_hash])


def restore_branch(repo_path: Path, branch: str) -> None:
    _run_git(["-C", str(repo_path), "checkout", "--force", branch])


def _run_git(args: list[str]) -> None:
    subprocess.run(["git", *args], check=True, text=True, capture_output=True)


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)
