"""Tests for Claude scheduled-task listing."""

from __future__ import annotations

from pathlib import Path

from connectors.claude_tasks import read_scheduled_tasks


def _make_task(root: Path, folder: str, skill_md: str | None) -> None:
    task_dir = root / folder
    task_dir.mkdir(parents=True)
    if skill_md is not None:
        (task_dir / "SKILL.md").write_text(skill_md)


def test_name_from_frontmatter(tmp_path: Path) -> None:
    _make_task(
        tmp_path,
        "scan-folder",
        "---\nname: skills-scan\ndescription: Recurring scan\n---\nbody text\n",
    )

    tasks = read_scheduled_tasks(tmp_path)

    assert len(tasks) == 1
    assert tasks[0].name == "skills-scan"
    assert tasks[0].schedule is None
    assert tasks[0].next_run is None


def test_missing_skill_md_uses_folder_name(tmp_path: Path) -> None:
    _make_task(tmp_path, "weekly-report", None)

    tasks = read_scheduled_tasks(tmp_path)

    assert tasks[0].name == "weekly-report"


def test_unparsable_frontmatter_uses_folder_name(tmp_path: Path) -> None:
    _make_task(tmp_path, "broken", "no frontmatter here\njust body")

    tasks = read_scheduled_tasks(tmp_path)

    assert tasks[0].name == "broken"


def test_multiple_folders(tmp_path: Path) -> None:
    _make_task(tmp_path, "a", "---\nname: task-a\n---\n")
    _make_task(tmp_path, "b", "---\nname: task-b\n---\n")
    _make_task(tmp_path, "c", None)

    tasks = read_scheduled_tasks(tmp_path)

    assert {t.name for t in tasks} == {"task-a", "task-b", "c"}


def test_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert read_scheduled_tasks(tmp_path / "nope") == []
