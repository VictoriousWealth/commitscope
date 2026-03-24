from datetime import datetime

from commitscope.config import RepoConfig
from commitscope.git.repository import _parse_dt, clone_or_update_repository, repo_name_from_url


def test_repo_name_from_url_handles_git_suffix() -> None:
    assert repo_name_from_url("https://github.com/example/project.git") == "project"


def test_repo_name_from_url_falls_back_for_empty_path() -> None:
    assert repo_name_from_url("https://github.com/") == "repository"


def test_parse_dt_returns_datetime_for_iso_string() -> None:
    assert _parse_dt("2026-03-22T10:15:00") == datetime(2026, 3, 22, 10, 15, 0)


def test_parse_dt_returns_none_for_missing_value() -> None:
    assert _parse_dt(None) is None


def test_clone_or_update_repository_clones_when_repo_missing(tmp_path, monkeypatch) -> None:
    config = RepoConfig(
        url="https://github.com/example/project.git",
        branch="main",
        max_commits=5,
        checkout_root=str(tmp_path),
    )
    calls: list[list[str]] = []

    monkeypatch.setattr("commitscope.git.repository._run_git", lambda args: calls.append(args))

    repo_path = clone_or_update_repository(config)

    assert repo_path == tmp_path / "project"
    assert calls == [["clone", "--branch", "main", "--single-branch", config.url, str(repo_path)]]


def test_clone_or_update_repository_fetches_and_pulls_when_repo_exists(tmp_path, monkeypatch) -> None:
    config = RepoConfig(
        url="https://github.com/example/project.git",
        branch="main",
        max_commits=5,
        checkout_root=str(tmp_path),
    )
    repo_path = tmp_path / "project"
    repo_path.mkdir()
    calls: list[list[str]] = []

    monkeypatch.setattr("commitscope.git.repository._run_git", lambda args: calls.append(args))

    returned = clone_or_update_repository(config)

    assert returned == repo_path
    assert calls == [
        ["-C", str(repo_path), "fetch", "--all", "--tags", "--prune"],
        ["-C", str(repo_path), "checkout", "main"],
        ["-C", str(repo_path), "pull", "--ff-only", "origin", "main"],
    ]

