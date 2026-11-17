"""Project history and approval state, kept as small JSON files under docs/data/.

docs/data/index.json            newest-first summaries (what the dashboard lists)
docs/data/projects/<id>.json    one full record per project (no binaries)
docs/data/ideas.json            latest research output
Videos themselves live in GitHub Releases, not in git.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .util import PipelineError, write_json

ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]{1,40}$")
DECISIONS = {"approve": "approved", "reject": "rejected"}


def check_id(pid: str) -> str:
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise PipelineError("Invalid project id.")
    return pid


def now_iso(now=None) -> str:
    return (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _index_path(data_dir) -> Path:
    return Path(data_dir) / "index.json"


def load_index(data_dir) -> dict:
    try:
        data = json.loads(_index_path(data_dir).read_text(encoding="utf-8"))
        if isinstance(data.get("projects"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"projects": []}


def summary(project: dict) -> dict:
    return {"id": project["id"], "title": project.get("title") or project.get("topic", ""),
            "topic": project.get("topic", ""), "style": project.get("style", ""),
            "duration_target": project.get("duration_target"), "status": project["status"],
            "created_at": project["created_at"],
            "qa_status": (project.get("qa") or {}).get("status", ""),
            "thumbnail_url": (project.get("assets") or {}).get("thumbnail_url", "")}


def save_project(data_dir, project: dict) -> None:
    check_id(project["id"])
    write_json(Path(data_dir) / "projects" / f"{project['id']}.json", project)
    index = load_index(data_dir)
    rows = [r for r in index["projects"] if r.get("id") != project["id"]] + [summary(project)]
    index["projects"] = sorted(rows, key=lambda r: r["created_at"], reverse=True)
    write_json(_index_path(data_dir), index)


def get_project(data_dir, pid: str) -> dict:
    check_id(pid)
    try:
        return json.loads((Path(data_dir) / "projects" / f"{pid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PipelineError(f"Project {pid} not found.") from None


def set_status(data_dir, pid: str, decision: str, note: str = "", now=None) -> dict:
    if decision not in DECISIONS:
        raise PipelineError("Decision must be 'approve' or 'reject'.")
    project = get_project(data_dir, pid)
    if project["status"] in ("failed", "qa_failed"):
        raise PipelineError(f"Project is '{project['status']}' and cannot be approved or rejected.")
    if (project.get("qa") or {}).get("status") == "fail":
        raise PipelineError("Quality checks failed; this project cannot be approved.")
    project["status"] = DECISIONS[decision]
    project["approval"] = {"decision": DECISIONS[decision], "at": now_iso(now), "note": note[:300]}
    save_project(data_dir, project)
    return project


def save_ideas(data_dir, ideas: dict) -> None:
    write_json(Path(data_dir) / "ideas.json", ideas)
