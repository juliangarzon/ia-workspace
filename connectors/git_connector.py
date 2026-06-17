"""Read-only git/project monitoring.

Reads the local git state for configured project directories without ever
fetching or writing. Each project yields a :class:`~app.models.Project`. Every
git command runs independently so one failure (e.g. no upstream) does not block
the others, and non-git or missing directories degrade to a clean partial
state rather than raising.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.models import Project

_GIT_TIMEOUT_SECONDS = 5


def _run_git(path: Path, args: list[str]) -> str | None:
    """Run a read-only git command, returning stripped stdout or ``None``.

    Returns ``None`` on any failure: non-zero exit, timeout, or missing git.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return result.stdout.strip()


def _branch(path: Path) -> str | None:
    return _run_git(path, ["rev-parse", "--abbrev-ref", "HEAD"]) or None


def _dirty(path: Path) -> bool | None:
    status = _run_git(path, ["status", "--porcelain"])
    if status is None:
        return None
    # Ignore untracked files (lines starting with "??")
    tracked_changes = [l for l in status.splitlines() if not l.startswith("??")]
    return bool(tracked_changes)


def _ahead_behind(path: Path) -> tuple[int | None, int | None]:
    output = _run_git(path, ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
    if not output:
        return None, None
    parts = output.split()
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def _last_commit(path: Path) -> tuple[str | None, datetime | None]:
    output = _run_git(path, ["log", "-1", "--format=%H|%s|%aI"])
    if not output:
        return None, None
    parts = output.split("|", 2)
    if len(parts) != 3:
        return None, None
    message = parts[1]
    try:
        committed_at = datetime.fromisoformat(parts[2]).astimezone(timezone.utc)
    except ValueError:
        committed_at = None
    return message, committed_at


def _last_activity_at(path: Path) -> datetime | None:
    """Most recent file mtime in the working tree, excluding ``.git/``."""
    latest: float | None = None
    for root, dirs, files in os.walk(path):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in files:
            try:
                mtime = os.stat(os.path.join(root, name)).st_mtime
            except OSError:
                continue
            if latest is None or mtime > latest:
                latest = mtime
    if latest is None:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc)


def read_project(path: Path) -> Project:
    """Read git state for one project directory.

    Read-only: no fetch, no write. Non-git or missing directories return a
    clean partial state (``None`` fields) rather than raising. Each field is
    gathered independently so a single failure does not blank the others.
    """
    ahead, behind = _ahead_behind(path)
    last_commit_message, last_commit_at = _last_commit(path)
    return Project(
        name=path.name,
        path=str(path),
        branch=_branch(path),
        dirty=_dirty(path),
        ahead=ahead,
        behind=behind,
        last_commit_message=last_commit_message,
        last_commit_at=last_commit_at,
        last_activity_at=_last_activity_at(path),
    )


def read_projects(project_paths: list[Path]) -> list[Project]:
    """Read all configured project paths."""
    return [read_project(path) for path in project_paths]
