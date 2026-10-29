"""Project registry: one isolated workspace per client engagement.

Layout under ``SEMLIFT_HOME``::

    projects.json                 registry (id -> name, client, path, status, created, created_by)
    projects/<id>/                one Workspace per project (uploads, runs, review, output, audit.jsonl)

A legacy single workspace (``SEMLIFT_WORKSPACE``) is registered as project ``default`` so existing
installations keep working without a migration.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import threading
from pathlib import Path

from .workspace import ReviewError, Workspace, _read_json, _write_json

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:63]


class ProjectRegistry:
    def __init__(self, home: str | Path, legacy_workspace: str | Path | None = None):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "projects").mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._workspaces: dict[str, Workspace] = {}
        self._run_locks: dict[str, threading.Lock] = {}
        if legacy_workspace:
            reg = self._read()
            if "default" not in reg:
                reg["default"] = {"id": "default", "name": "Default project", "client": "", "description":
                                  "Single workspace from SEMLIFT_WORKSPACE", "path": str(Path(legacy_workspace).resolve()),
                                  "status": "active", "created": _now(), "created_by": "system"}
                self._write(reg)

    # ------------------------------------------------------------ registry file
    @property
    def path(self) -> Path:
        return self.home / "projects.json"

    def _read(self) -> dict:
        return _read_json(self.path, {})

    def _write(self, reg: dict) -> None:
        _write_json(self.path, reg)

    # ------------------------------------------------------------ queries
    def list(self, include_archived: bool = False) -> list[dict]:
        out = []
        for p in sorted(self._read().values(), key=lambda p: (p.get("client", ""), p["name"])):
            if p.get("status") == "archived" and not include_archived:
                continue
            out.append(self._with_summary(p))
        return out

    def get(self, pid: str) -> dict:
        p = self._read().get(pid)
        if p is None:
            raise KeyError(pid)
        return self._with_summary(p)

    def exists(self, pid: str) -> bool:
        return pid in self._read()

    def _root(self, p: dict) -> Path:
        return Path(p["path"]) if p.get("path") else self.home / "projects" / p["id"]

    def _with_summary(self, p: dict) -> dict:
        return self.info(p["id"]) | {"summary": self.workspace(p["id"]).card()}

    def info(self, pid: str) -> dict:
        p = self._read().get(pid)
        if p is None:
            raise KeyError(pid)
        return {k: v for k, v in p.items() if k != "path"}

    def workspace(self, pid: str) -> Workspace:
        with self._lock:
            if pid not in self._workspaces:
                reg = self._read()
                if pid not in reg:
                    raise KeyError(pid)
                self._workspaces[pid] = Workspace(self._root(reg[pid]))
            return self._workspaces[pid]

    def run_lock(self, pid: str) -> threading.Lock:
        with self._lock:
            return self._run_locks.setdefault(pid, threading.Lock())

    # ------------------------------------------------------------ changes
    def create(self, name: str, client: str = "", description: str = "", pid: str | None = None,
               config: str | Path | None = None, created_by: str = "system") -> dict:
        if not name.strip():
            raise ReviewError("project name is required")
        pid = pid or slugify(f"{client}-{name}" if client else name)
        if not ID_RE.match(pid):
            raise ReviewError("project id must be 2-63 lower-case letters, digits or hyphens")
        with self._lock:
            reg = self._read()
            if pid in reg:
                raise ReviewError(f"project {pid} already exists")
            reg[pid] = {"id": pid, "name": name.strip(), "client": client.strip(), "description": description,
                        "status": "active", "created": _now(), "created_by": created_by}
            self._write(reg)
        ws = self.workspace(pid)
        if config:
            ws.set_config(config)
        return self.get(pid)

    def update(self, pid: str, **fields) -> dict:
        with self._lock:
            reg = self._read()
            if pid not in reg:
                raise KeyError(pid)
            for k in ("name", "client", "description", "status"):
                if fields.get(k) is not None:
                    reg[pid][k] = fields[k]
            if reg[pid]["status"] not in ("active", "archived"):
                raise ReviewError("status must be active or archived")
            self._write(reg)
        return self.get(pid)


_registry: tuple[tuple, ProjectRegistry] | None = None


def registry() -> ProjectRegistry:
    """Process-wide registry, rebuilt when the environment changes (tests switch homes)."""
    global _registry
    legacy = os.environ.get("SEMLIFT_WORKSPACE")
    home = os.environ.get("SEMLIFT_HOME") or (str(Path(legacy).resolve().parent / ".semlift_home") if legacy else "semlift_home")
    key = (home, legacy)
    if _registry is None or _registry[0] != key:
        _registry = (key, ProjectRegistry(home, legacy))
    return _registry[1]


def default_project_id() -> str | None:
    reg = registry()
    if reg.exists("default"):
        return "default"
    projects = reg.list()
    return projects[0]["id"] if len(projects) == 1 else None
