"""FastAPI application entrypoint for the workspace monitor."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.cache import SnapshotCache
from app.config import load_config
from app.registry import registry
from connectors.claude import ClaudeConnector
from connectors.docker_connector import DockerConnector


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    app.state.config = config
    registry.register(ClaudeConnector(config))
    registry.register(DockerConnector())
    project_paths = [Path(p) for p in config.projects]
    app.state.cache = SnapshotCache(config.cache_ttl_seconds, registry, project_paths)
    yield


app = FastAPI(title="Workspace Monitor", lifespan=lifespan)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    snapshot = app.state.cache.get().model_dump(mode="json")
    poll_ms = app.state.config.poll_interval_seconds * 1000
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "snapshot": snapshot,
            "poll_interval_ms": poll_ms,
        },
    )


@app.get("/api/snapshot")
async def snapshot() -> dict[str, object]:
    return app.state.cache.get().model_dump(mode="json")


@app.get("/api/docker")
async def get_docker() -> dict[str, object]:
    snapshot = app.state.cache.get()
    return {
        "containers": [c.model_dump(mode="json") for c in snapshot.docker_containers]
    }


@app.get("/api/projects/{name}")
async def get_project(name: str) -> dict[str, object]:
    snapshot = app.state.cache.get()
    project = next((p for p in snapshot.projects if p.name == name), None)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.model_dump(mode="json")


@app.post("/api/config/projects")
async def update_projects(paths: list[str] = Body(...)) -> dict[str, object]:
    config = app.state.config
    config_path = Path(__file__).resolve().parent.parent / "config.json"

    raw = json.loads(config_path.read_text())
    raw["projects"] = paths
    config_path.write_text(json.dumps(raw, indent=2))

    config.projects = paths
    app.state.cache.set_project_paths([Path(p) for p in paths])

    return {"ok": True, "projects": paths}


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    sources = {c.id: c.available() for c in registry.all()}
    return {
        "status": "ok",
        "sources": sources,
        "cache_age_seconds": app.state.cache.age_seconds(),
    }
