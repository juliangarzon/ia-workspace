"""List Claude scheduled tasks from ``<scheduled_tasks_dir>/<name>/SKILL.md``.

Each subfolder is one task. The ``SKILL.md`` frontmatter carries a ``name``
field; the files hold no cron data, so ``schedule`` and ``next_run`` are always
``None``. A missing or unparsable ``SKILL.md`` falls back to the folder name.
"""

from __future__ import annotations

from pathlib import Path

from app.models import ScheduledTask


def _frontmatter_name(skill_md: Path) -> str | None:
    """Extract the ``name:`` value from YAML frontmatter via string splitting."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    for line in parts[1].splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            value = stripped[len("name:") :].strip().strip("'\"")
            return value or None
    return None


def read_scheduled_tasks(scheduled_tasks_dir: Path) -> list[ScheduledTask]:
    """One entry per subfolder under ``scheduled_tasks_dir``.

    Reads ``SKILL.md`` frontmatter for the name, falling back to the folder
    name. ``schedule`` and ``next_run`` are always ``None``.
    """
    if not scheduled_tasks_dir.exists():
        return []

    tasks: list[ScheduledTask] = []
    for folder in sorted(scheduled_tasks_dir.iterdir()):
        if not folder.is_dir():
            continue
        name = _frontmatter_name(folder / "SKILL.md") or folder.name
        tasks.append(ScheduledTask(name=name, schedule=None, next_run=None))
    return tasks
