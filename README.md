# Workspace Monitor

A single-page dashboard for your local dev workspace. It watches three things at once: your Claude AI usage, your Docker containers, and your git projects. Runs in Docker, reads everything read-only, and refreshes itself in the browser.

Built for one machine: yours. No database, no auth, no cloud. Just a JSON config and a web page bound to localhost.

## What it shows

**AI usage (Claude)**
- Token consumption across three windows: 5-hour, weekly, monthly. When you set a quota limit, each window draws a usage bar; with no limit set, it just shows the raw count.
- Active sessions, each tagged active / idle / stale, with the git branch the session is working in.
- Scheduled tasks pulled from your skill frontmatter.

**Docker**
- Every container (running and stopped): status, CPU %, memory used vs limit, uptime, published ports.
- Strictly read-only. The dashboard never starts, stops, or changes a container.

**Git projects**
- Per project: current branch, clean or dirty (tracked files only — untracked files are ignored), commits ahead/behind upstream, last commit message, and last working-tree activity.
- Projects are configured from the UI, no rebuild needed.

The page polls the backend every 5 seconds. The backend serves a cached snapshot that it recomputes at most once per TTL window (default 60s), so polling stays cheap.

## Requirements

- macOS with [OrbStack](https://orbstack.dev/). The compose file mounts `~/.orbstack/run/docker.sock`. On plain Docker Desktop you'd point that volume at a different socket path.
- `git` — already installed inside the container by the Dockerfile. You don't need it on the host for the dashboard to work.

## Quick start

```bash
docker compose up --build
```

Open http://127.0.0.1:8000. The port is bound to `127.0.0.1` only, never `0.0.0.0` — the dashboard is not reachable from your network.

To check health and which connectors are live:

```bash
curl http://127.0.0.1:8000/healthz
```

## Configuration

Everything lives in `config.json` at the project root. It's mounted read-write into the container, so changes survive restarts and the Projects tab can write back to it.

```json
{
  "poll_interval_seconds": 5,
  "cache_ttl_seconds": 60,
  "claude_state_path": "~/.claude",
  "projects": [
    "/host/workera_webapps",
    "/host/data_platform_sage"
  ],
  "quota_limits": {
    "five_hour": null,
    "weekly": null,
    "monthly": null
  }
}
```

| Key | Meaning |
|-----|---------|
| `poll_interval_seconds` | How often the browser asks the backend for a fresh snapshot. |
| `cache_ttl_seconds` | How long the backend reuses a computed snapshot before recomputing. |
| `claude_state_path` | Where Claude state lives. Inside the container this resolves under `/root/.claude`. |
| `projects` | Container-side paths to monitor. See "Adding a project" below. |
| `quota_limits` | Token ceilings per window. `null` means no limit — the window shows a raw count instead of a bar. |

Set a quota limit to turn a window into a progress bar:

```json
"quota_limits": { "five_hour": 200000, "weekly": 2000000, "monthly": null }
```

## Adding a project

Two steps, because the container can only see paths you mount into it.

**1. Mount the host directory** in `docker-compose.yml` under `/host/`, read-only:

```yaml
volumes:
  - "${HOME}/Env/my_project:/host/my_project:ro"
```

The `/host/` prefix is just a convention to keep mounted project paths together and obviously distinct from the app's own files. Mounting requires editing compose and recreating the container (`docker compose up -d`).

**2. Register the path in the UI.** Open the Projects tab and add the *container* path (`/host/my_project`, not the host path). The dashboard writes it to `config.json` and starts monitoring immediately — no rebuild.

If you add a project to `config.json` whose path isn't mounted, it shows up with empty git fields rather than erroring.

## How it works

- **FastAPI + Jinja2.** One server-rendered page plus a few JSON endpoints (`/api/snapshot`, `/api/docker`, `/api/projects/{name}`).
- **Pluggable connectors.** Each data source (Claude, Docker — Codex is planned) is a connector behind a common interface. They register at startup and every `collect()` swallows its own errors, so one broken source can't take down the page.
- **Snapshot cache.** A single in-process cache with a TTL fronts all connectors. The browser polls fast; the expensive work runs slow.
- **No database.** State is `config.json` plus whatever the connectors read live from disk and the Docker socket.

### Token accounting

The Claude connector parses every transcript JSONL under the projects directory. Streaming responses repeat the same `message.id` across many lines, so it dedupes on `message.id` — without that, tokens get counted several times and every window inflates.

### Read-only by design

- Docker socket is mounted `:ro` and the connector only ever issues `list` / `stats` / `attrs` calls.
- Git monitoring shells out to read-only commands (`status`, `rev-parse`, `rev-list`, `log`) with a 5s timeout each, never `fetch` or anything that writes.
- Claude and Codex state directories are mounted `:ro`.

The one writable mount is `config.json`, so the Projects tab can persist your project list.

## Security notes

This is a local dev tool and makes the matching tradeoffs:

- **Runs as root inside the container.** Fine for a single-user tool on your own machine; not something you'd ship.
- **No authentication.** Mitigated by binding to `127.0.0.1` only.
- **`:ro` on the docker socket is load-bearing.** Drop it and you've handed the container full control of the Docker daemon, which on macOS is effectively host root. Don't.

## Development

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
ruff check .
pytest
```

Running outside Docker means paths like `~/.claude` resolve on your host, and Docker container stats use whatever socket `docker.from_env()` finds. Point `claude_state_path` and `projects` at real host paths for a local run.

## Project layout

```
app/
  main.py        # FastAPI app, routes, lifespan wiring
  config.py      # config.json loading, typed Config model
  cache.py       # snapshot cache with TTL
  registry.py    # connector registry
  models.py      # Pydantic models for snapshots, projects, containers
  templates/     # Jinja2 single-page UI
connectors/
  base.py            # Connector interface
  claude*.py         # Claude: token windows, sessions, tasks, JSONL parser
  docker_connector.py
  git_connector.py
config.json      # the only thing you edit
docker-compose.yml
Dockerfile
```
