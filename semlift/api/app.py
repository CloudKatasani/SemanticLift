"""FastAPI service behind the SemanticLift web UI (spec 8.2)."""
from __future__ import annotations

import io
import logging
import os
import time
import uuid
import zipfile
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..config import validate_config
from ..service import jobs
from ..service.identity import ROLE_HELP, ROLES, AuthError, Identity, auth_mode, resolve_identity
from ..service.projects import default_project_id, registry
from ..service.workspace import ReviewError, Workspace

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("SEMLIFT_CONFIG_DIR", ROOT / "config"))
UI_DIST = Path(os.environ.get("SEMLIFT_UI_DIST", ROOT / "ui" / "dist"))

app = FastAPI(title="SemanticLift", version=__version__,
              description="Cognos-to-Data-Platform Semantic Layer Migrator")
app.add_middleware(GZipMiddleware, minimum_size=2048)
_ws: Workspace | None = None   # kept for backward compatibility; workspaces now come from the project registry
log = logging.getLogger("semlift.api")


# --------------------------------------------------------------------------- request context
@dataclass
class Ctx:
    ident: Identity
    project: str
    ws: Workspace


_CTX: ContextVar[Ctx | None] = ContextVar("semlift_ctx", default=None)


def ctx() -> Ctx:
    c = _CTX.get()
    if c is None:
        raise HTTPException(400, "no project in this request")
    return c


def ws() -> Workspace:
    return ctx().ws


def _identity(request: Request) -> Identity:
    try:
        ident = resolve_identity(request.headers)
    except AuthError as e:
        raise HTTPException(e.status, str(e))
    request.state.user = ident.name
    return ident


async def signed_in(request: Request) -> Identity:
    return _identity(request)


def need(role: str):
    """Dependency: resolve identity + project (X-SemLift-Project header or ?project=) and check the role.

    Async on purpose: the context variable it sets is copied into the worker thread of sync endpoints."""
    async def dep(request: Request) -> Ctx:
        ident = _identity(request)
        pid = request.headers.get("x-semlift-project") or request.query_params.get("project") or default_project_id()
        if not pid:
            raise HTTPException(400, "no project selected - choose or create a project")
        reg = registry()
        if not reg.exists(pid) or not ident.can("viewer", pid):
            raise HTTPException(404, f"unknown project {pid}")
        if not ident.can(role, pid):
            raise HTTPException(403, f"{role} role required in project {pid} ({ROLE_HELP[role]})")
        if role != "viewer" and reg.info(pid).get("status") == "archived":
            raise HTTPException(409, f"project {pid} is archived (read-only)")
        request.state.project = pid
        c = Ctx(ident, pid, reg.workspace(pid))
        _CTX.set(c)
        return c
    return dep


def who(body_reviewer: str | None = None) -> str:
    """Reviewer name comes from the signed-in identity; the request body is trusted only in open mode."""
    c = ctx()
    if c.ident.mode == "open" and body_reviewer and body_reviewer not in ("steward", "auto"):
        return body_reviewer
    return c.ident.name


def record(action: str, subject: str = "", **detail) -> None:
    c = ctx()
    c.ws.audit(c.ident.name, action, subject, {k: v for k, v in detail.items() if v not in (None, "")})


@app.middleware("http")
async def access_log(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    t = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    if request.url.path.startswith("/api/"):
        log.info("%s %s %s %.0fms user=%s project=%s rid=%s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - t) * 1000, getattr(request.state, "user", "-"),
                 getattr(request.state, "project", "-"), rid)
    return response


def state() -> dict:
    st = ws().state()
    if not st:
        raise HTTPException(404, "no run yet - upload a bundle and run the pipeline")
    return st


@app.exception_handler(ReviewError)
async def _review_error(_req, exc: ReviewError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


class RunRequest(BaseModel):
    config: Optional[str] = None
    overrides: Optional[dict] = None
    source: Optional[str] = None


class ReviewRequest(BaseModel):
    action: str
    ddl: Optional[str] = None
    reviewer: str = "steward"
    comment: str = ""
    acknowledge_low_confidence: bool = False


class FindingUpdate(BaseModel):
    owner: Optional[str] = None
    status: Optional[str] = None


class SuggestionDecision(BaseModel):
    status: str
    description: Optional[str] = None
    synonyms: Optional[list[str]] = None


class ReportDecision(BaseModel):
    disposition: Optional[str] = None
    comment: str = ""
    target: Optional[str] = None
    reviewer: str = "steward"


class KpiDecision(BaseModel):
    variant: Optional[str] = None
    comment: str = ""
    reviewer: str = "steward"


class SourceDecision(BaseModel):
    scope: Optional[str] = None
    comment: str = ""
    reviewer: str = "steward"


class DeployRequest(BaseModel):
    branch: Optional[str] = None
    push: bool = False
    remote: Optional[str] = None


class Settings(BaseModel):
    git_remote: Optional[str] = None


# --------------------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "environment": os.environ.get("SEMLIFT_ENV", "development"),
            "auth_mode": auth_mode()}


class ProjectCreate(BaseModel):
    name: str
    client: str = ""
    description: str = ""
    id: Optional[str] = None
    config: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    client: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


@app.get("/api/me")
def me(request: Request, ident: Identity = Depends(signed_in)):
    pid = request.headers.get("x-semlift-project") or request.query_params.get("project") or default_project_id()
    return ident.public(pid) | {"project": pid if pid and registry().exists(pid) else None,
                                "role_help": ROLE_HELP, "all_roles": list(ROLES)}


@app.get("/api/projects")
def list_projects(include_archived: bool = False, ident: Identity = Depends(signed_in)):
    return [p | {"my_roles": sorted(ident.roles_for(p["id"]), key=ROLES.index)}
            for p in registry().list(include_archived) if ident.can("viewer", p["id"])]


@app.post("/api/projects")
def create_project(req: ProjectCreate, ident: Identity = Depends(signed_in)):
    if not ident.is_admin():
        raise HTTPException(403, "admin role required to create projects")
    cfg = None
    if req.config:
        cfg = CONFIG_DIR / f"{Path(req.config).stem}.yaml"
        if not cfg.exists():
            raise HTTPException(404, f"config {req.config} not found")
    p = registry().create(req.name, req.client, req.description, req.id, cfg, created_by=ident.name)
    registry().workspace(p["id"]).audit(ident.name, "project.create", p["id"],
                                        {"name": p["name"], "client": p["client"], "config": req.config})
    return p


@app.patch("/api/projects/{pid}")
def update_project(pid: str, req: ProjectUpdate, ident: Identity = Depends(signed_in)):
    if not ident.can("admin", pid):
        raise HTTPException(403, "admin role required")
    if not registry().exists(pid):
        raise HTTPException(404, f"unknown project {pid}")
    p = registry().update(pid, **req.model_dump())
    registry().workspace(pid).audit(ident.name, "project.update", pid, req.model_dump(exclude_none=True))
    return p


@app.get("/api/audit", dependencies=[Depends(need("viewer"))])
def audit(limit: int = 200, offset: int = 0, action: Optional[str] = None, user: Optional[str] = None):
    return ws().audit_log(min(limit, 2000), offset, action, user)


@app.get("/api/configs", dependencies=[Depends(signed_in)])
def configs():
    return sorted(p.stem for p in CONFIG_DIR.glob("*.yaml"))


@app.get("/api/settings", dependencies=[Depends(need("viewer"))])
def get_settings():
    return ws().settings()


@app.put("/api/settings", dependencies=[Depends(need("admin"))])
def put_settings(s: Settings):
    ws().save_settings(s.model_dump(exclude_none=True))
    record("settings.update", "settings", **s.model_dump(exclude_none=True))
    return ws().settings()


# --------------------------------------------------------------------------- ingest / run
@app.get("/api/uploads", dependencies=[Depends(need("viewer"))])
def uploads():
    d = ws().root / "uploads"
    return [{"name": p.name, "size": p.stat().st_size} for p in sorted(d.iterdir()) if p.is_file()]


@app.post("/api/uploads", dependencies=[Depends(need("analyst"))])
async def upload(files: list[UploadFile] = File(...), reset: bool = False):
    if reset:
        ws().clear_uploads()
    saved = []
    for f in files:
        data = await f.read()
        p = ws().add_upload(f.filename or "upload.bin", data)
        saved.append({"name": p.name, "size": len(data)})
    record("upload.add", ", ".join(x["name"] for x in saved), reset=reset or None,
           bytes=sum(x["size"] for x in saved))
    return saved


@app.delete("/api/uploads", dependencies=[Depends(need("analyst"))])
def clear_uploads():
    ws().clear_uploads()
    record("upload.clear")
    return []


def _prepare_run(req: RunRequest):
    base = None
    if req.config:
        cand = CONFIG_DIR / f"{Path(req.config).stem}.yaml"
        if not cand.exists():
            raise HTTPException(404, f"config {req.config} not found")
        base = cand
    if base or req.overrides or not ws().config_path.exists():
        ws().set_config(base, req.overrides)
    src = None
    if req.source:
        p = (ROOT / req.source).resolve()
        if not str(p).startswith(str(ROOT)) or not p.exists():
            raise HTTPException(400, "source must be a path inside the application folder")
        src = p
    return src


def _do_run(w: Workspace, src, user: str, kind: str) -> dict:
    t = time.perf_counter()
    st = w.run(src)
    out = summary_of(st) | {"config_warnings": validate_config(w.config())}
    w.audit(user, f"pipeline.{kind}", st["run_id"], {"objects": out["objects"], "findings": out["findings"],
                                                      "seconds": round(time.perf_counter() - t, 1)})
    return out


def _sync(kind: str, src=None) -> dict:
    c = ctx()
    if jobs.active(c.project):
        raise HTTPException(409, "a run is already in progress for this project")
    lock = registry().run_lock(c.project)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "a run is already in progress for this project")
    try:
        return _do_run(c.ws, src, c.ident.name, kind)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        lock.release()


def _submit(kind: str, src=None) -> dict:
    c = ctx()
    try:
        return jobs.submit(c.project, kind, c.ident.name, lambda: _do_run(c.ws, src, c.ident.name, kind),
                           registry().run_lock(c.project))
    except jobs.Busy as e:
        raise HTTPException(409, str(e))


@app.post("/api/run", dependencies=[Depends(need("analyst"))])
def run(req: RunRequest):
    """Synchronous run (CLI, scripts, tests). The UI uses POST /api/jobs/run."""
    return _sync("run", _prepare_run(req))


@app.post("/api/jobs/run", dependencies=[Depends(need("analyst"))])
def run_job(req: RunRequest):
    if not (ws().root / "uploads").exists() or not any((ws().root / "uploads").iterdir()):
        raise HTTPException(400, "No input files uploaded")
    return _submit("run", _prepare_run(req))


@app.post("/api/jobs/rerun", dependencies=[Depends(need("analyst"))])
def rerun_job():
    if not ws().state():
        raise HTTPException(404, "no run yet - upload a bundle and run the pipeline")
    return _submit("rerun")


@app.get("/api/jobs", dependencies=[Depends(need("viewer"))])
def list_jobs():
    return jobs.recent(ctx().project)


@app.get("/api/jobs/{job_id}", dependencies=[Depends(need("viewer"))])
def job(job_id: str):
    j = jobs.get(job_id)
    if j is None or j["project"] != ctx().project:
        raise HTTPException(404, "unknown job")
    return j


def summary_of(st: dict) -> dict:
    return {"run_id": st["run_id"], "time": st["time"], "tool_version": st["tool_version"], "timings": st["timings"],
            "counts": st["ingest"]["counts"], "rationalization": st["estate"]["rationalization"],
            "review_summary": st["review_summary"], "objects": len(st["objects"]), "findings": len(st["findings"]),
            "entities": len(st["model"]["entities"]), "aggregates": len(st["aggregates"]["plans"]),
            "semantic_views": sum(1 for o in st["objects"] if o["object_type"] == "semantic view"),
            "products": len(st["products"]), "validation": st["validation"], "diff": st["diff"]}


@app.get("/api/summary", dependencies=[Depends(need("viewer"))])
def summary():
    c = ctx()
    naming = c.ws.config().get("naming", {})
    return summary_of(state()) | {"project": registry().info(c.project),
                                  "display": {"package_affixes": naming.get("package_affixes", [])}}


@app.get("/api/ingest", dependencies=[Depends(need("viewer"))])
def ingest():
    return state()["ingest"]


@app.get("/api/estate", dependencies=[Depends(need("viewer"))])
def estate():
    return state()["estate"]


@app.get("/api/model", dependencies=[Depends(need("viewer"))])
def model():
    return state()["model"]


@app.get("/api/logical-model", dependencies=[Depends(need("viewer"))])
def logical_model():
    st = state()
    if "logical" not in st:
        raise HTTPException(404, "logical model not in this run - re-run the pipeline")
    return st["logical"]


@app.get("/api/lineage", dependencies=[Depends(need("viewer"))])
def lineage():
    state()
    p = ws().root / "lineage_index.json"
    if not p.exists():
        raise HTTPException(404, "lineage not in this run - re-run the pipeline")
    return FileResponse(p, media_type="application/json")


# --------------------------------------------------------------------------- portfolio pages
@app.get("/api/portfolio", dependencies=[Depends(need("viewer"))])
def portfolio():
    state()
    return ws().portfolio_view()


@app.post("/api/portfolio/{report}", dependencies=[Depends(need("steward"))])
def decide_report(report: str, d: ReportDecision):
    out = ws().decide_report(report, d.disposition, d.comment, d.target, who(d.reviewer))
    record("decision.report", report, disposition=d.disposition or "(cleared)", target=d.target, comment=d.comment)
    return out


@app.get("/api/kpis", dependencies=[Depends(need("viewer"))])
def kpis():
    state()
    return ws().kpi_view()


@app.post("/api/kpis/{group_id}", dependencies=[Depends(need("steward"))])
def decide_kpi(group_id: str, d: KpiDecision):
    out = ws().decide_kpi(group_id, d.variant, d.comment, who(d.reviewer))
    record("decision.kpi", group_id, variant=d.variant or "(cleared)", comment=d.comment)
    return out


@app.get("/api/sources", dependencies=[Depends(need("viewer"))])
def sources():
    state()
    return ws().sources_view()


@app.post("/api/sources/{table_id:path}", dependencies=[Depends(need("steward"))])
def decide_source(table_id: str, d: SourceDecision):
    out = ws().decide_source(table_id, d.scope, d.comment, who(d.reviewer))
    record("decision.source", table_id, scope=d.scope or "(cleared)", comment=d.comment)
    return out


@app.get("/api/products-view", dependencies=[Depends(need("viewer"))])
def products_view():
    state()
    return ws().view("products") | {"pending_rerun": ws().decisions_pending()}


@app.get("/api/objects-lineage", dependencies=[Depends(need("viewer"))])
def objects_lineage():
    state()
    return ws().view("objects")


@app.get("/api/story", dependencies=[Depends(need("viewer"))])
def story():
    state()
    return ws().story_view()


@app.post("/api/rerun", dependencies=[Depends(need("analyst"))])
def rerun():
    """Re-run the pipeline on the uploaded bundle so steward decisions reach the design (synchronous)."""
    return _sync("rerun")


@app.get("/api/findings", dependencies=[Depends(need("viewer"))])
def findings():
    st = state()
    return {"findings": st["findings"], "numbers_that_change": st["numbers_that_change"], "validation": st["validation"]}


@app.patch("/api/findings/{finding_id}", dependencies=[Depends(need("steward"))])
def update_finding(finding_id: str, u: FindingUpdate):
    out = ws().update_finding(finding_id, owner=u.owner, status=u.status)
    record("finding.update", finding_id, owner=u.owner, status=u.status)
    return out


# --------------------------------------------------------------------------- design review
@app.get("/api/objects", dependencies=[Depends(need("viewer"))])
def objects(layer: Optional[str] = None):
    st = state()
    out = [{k: v for k, v in o.items() if k not in ("edited_ddl",)} | {"edited": bool(o.get("edited_ddl"))}
           for o in st["objects"] if not layer or o["layer"] == layer]
    return {"objects": out, "summary": st["review_summary"]}


@app.get("/api/objects/{object_id:path}", dependencies=[Depends(need("viewer"))])
def object_detail(object_id: str):
    st = state()
    o = next((x for x in st["objects"] if x["id"] == object_id), None)
    if o is None:
        raise HTTPException(404, "unknown object")
    ddl = (ws().output / o["file"]).read_text(encoding="utf-8")
    return o | {"ddl": ddl}


@app.post("/api/objects/{object_id:path}/review", dependencies=[Depends(need("approver"))])
def review(object_id: str, r: ReviewRequest):
    out = ws().review(object_id, r.action, reviewer=who(r.reviewer), comment=r.comment, ddl=r.ddl,
                      acknowledge_low_confidence=r.acknowledge_low_confidence)
    record(f"object.{r.action}", object_id, comment=r.comment, acknowledged_low_confidence=r.acknowledge_low_confidence or None)
    return out


@app.post("/api/approve-all", dependencies=[Depends(need("approver"))])
def approve_all():
    out = ws().auto_approve(reviewer=f"{who()} (bulk)")
    record("object.approve_all", "", approved=out["approved"])
    return out


@app.get("/api/suggestions", dependencies=[Depends(need("viewer"))])
def suggestions():
    return sorted(ws().suggestions().values(), key=lambda s: s["target"])


@app.post("/api/suggestions/{sug_id}", dependencies=[Depends(need("steward"))])
def decide(sug_id: str, d: SuggestionDecision):
    out = ws().decide_suggestion(sug_id, d.status, d.description, d.synonyms)
    record("suggestion.decide", sug_id, status=d.status)
    return out


@app.get("/api/aggregates", dependencies=[Depends(need("viewer"))])
def aggregates():
    st = state()
    agg = st["aggregates"]
    used = {d["cluster"] for f in agg["facts"].values() for d in f["demand"]}
    groups = {c["id"]: {"canonical": c["canonical"], "members": len(c["members"]), "package": c["package"],
                        "runs_per_day": c["runs_per_day"]} for c in st["estate"]["clusters"] if c["id"] in used}
    keys = ("coverage_target", "max_per_fact", "min_aggregate_coverage", "min_reduction_ratio", "plain_view_below_rows",
            "default_fact_rows", "warehouse", "low_volume_domains")
    return agg | {"groups": groups, "settings": {k: ws().config()["aggregates"].get(k) for k in keys}}


@app.get("/api/products", dependencies=[Depends(need("viewer"))])
def products():
    return state()["products"]


@app.get("/api/diff", dependencies=[Depends(need("viewer"))])
def diff():
    return state()["diff"]


# --------------------------------------------------------------------------- deploy & validate
@app.get("/api/deploy", dependencies=[Depends(need("viewer"))])
def deploy_status():
    st = state()
    return {"deploy": st.get("deploy"), "parity": st.get("parity"), "review_summary": st["review_summary"],
            "environment": os.environ.get("SEMLIFT_ENV", "development"), "settings": ws().settings()}


@app.post("/api/deploy", dependencies=[Depends(need("deployer"))])
def deploy(req: DeployRequest):
    # The UI only ever writes a Git branch; execution against Snowflake happens in CI (FR-13).
    c = ctx()
    out = c.ws.deploy(branch=req.branch, push=req.push, remote=req.remote,
                      author=f"{c.ident.name} <{c.ident.email or 'semlift@localhost'}>")
    record("deploy.git", out["branch"], commit=out["commit"], pushed=out["pushed"], objects=len(out["deployed"]))
    return out


@app.post("/api/parity", dependencies=[Depends(need("deployer"))])
def parity():
    out = ws().run_parity()
    record("parity.run", "", results=len(out.get("results", [])))
    return out


# --------------------------------------------------------------------------- downloads
def _safe(rel: str) -> Path:
    out = ws().output.resolve()
    p = (out / rel).resolve()
    if not str(p).startswith(str(out) + os.sep) or not p.is_file():
        raise HTTPException(404, "file not found")
    return p


@app.get("/api/files", dependencies=[Depends(need("viewer"))])
def files():
    return state()["files"]


@app.get("/api/files/{rel:path}", dependencies=[Depends(need("viewer"))])
def file(rel: str):
    p = _safe(rel)
    if p.suffix in (".xlsx",):
        return FileResponse(p, filename=p.name)
    return PlainTextResponse(p.read_text(encoding="utf-8"))


@app.get("/api/download/package", dependencies=[Depends(need("viewer"))])
def download_package():
    out = ws().output
    if not out.exists():
        raise HTTPException(404, "no package")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(out).as_posix())
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=semlift_design_package.zip"})


@app.get("/api/download/workbook", dependencies=[Depends(need("viewer"))])
def download_workbook():
    return FileResponse(_safe("design_workbook.xlsx"), filename="design_workbook.xlsx")


@app.get("/api/download/findings", dependencies=[Depends(need("viewer"))])
def download_findings():
    p = _safe("findings.md")
    return Response(p.read_bytes(), media_type="text/markdown",
                    headers={"Content-Disposition": "attachment; filename=findings.md"})


# --------------------------------------------------------------------------- UI
if UI_DIST.exists():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
else:
    @app.get("/")
    def root():
        return {"app": "SemanticLift", "version": __version__, "ui": "not built - run `npm run build` in ui/", "docs": "/docs"}
