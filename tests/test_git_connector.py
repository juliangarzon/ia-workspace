"""Tests for the read-only git connector.

These exercise real git state against the repo itself and against ordinary
directories. The connector never fetches or writes, so running against a live
repo is safe.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.models import Project
from connectors.git_connector import read_project, read_projects


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def test_clean_repo_reports_branch_and_dirty(git_repo: Path) -> None:
    project = read_project(git_repo)

    assert isinstance(project, Project)
    assert isinstance(project.branch, str)
    assert project.branch != ""
    assert isinstance(project.dirty, bool)
    assert project.dirty is False
    assert project.last_commit_message == "initial commit"
    assert project.last_commit_at is not None


def test_non_git_dir_returns_partial_state(tmp_path: Path) -> None:
    project = read_project(tmp_path)

    assert isinstance(project, Project)
    assert project.branch is None
    assert project.dirty is None
    assert project.ahead is None
    assert project.behind is None
    assert project.last_commit_message is None
    assert project.last_commit_at is None


def test_read_projects_empty() -> None:
    assert read_projects([]) == []


def test_missing_dir_all_none() -> None:
    missing = Path("/tmp/this-path-does-not-exist-workspace-monitor")

    project = read_project(missing)

    assert isinstance(project, Project)
    assert project.branch is None
    assert project.dirty is None
    assert project.ahead is None
    assert project.behind is None
    assert project.last_commit_message is None
    assert project.last_commit_at is None
    assert project.last_activity_at is None
