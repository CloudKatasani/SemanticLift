"""FastAPI service behind the SemLift web UI (spec 8.2)."""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..service.workspace import ReviewError, Workspace

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("SEMLIFT_CONFIG_DIR", ROOT / "config"))
UI_DIST = Path(os.environ.get("SEMLIFT_UI_DIST", ROOT / "ui" / "dist"))

app = FastAPI(title="SemLift", version=__version__,
              description="Cognos-to-Data-Platform Semantic Layer Migrator")
app.add_middleware(GZipMiddleware, minimum_size=2048)
_ws: Workspace | None = None


def ws() -> Workspace:
    global _ws
    if _ws is None:
        _ws = Workspace(os.environ.get("SEMLIFT_WORKSPACE", "workspace"))
    return _ws


def auth(authorization: Optional[str] = Header(default=None)) -> None:
    token = os.environ.get("SEMLIFT_API_TOKEN")
    if token and authorization != f"Bearer {token}":
        raise HTTPException(401, "invalid or missing token")


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
    return {"status": "ok", "version": __version__, "environment": os.environ.get("SEMLIFT_ENV", "development")}


@app.get("/api/configs", dependencies=[Depends(auth)])
def configs():
    return sorted(p.stem for p in CONFIG_DIR.glob("*.yaml"))


@app.get("/api/settings", dependencies=[Depends(auth)])
def get_settings():
    return ws().settings()


@app.put("/api/settings", dependencies=[Depends(auth)])
def put_settings(s: Settings):
    ws().save_settings(s.model_dump(exclude_none=True))
    return ws().settings()


# --------------------------------------------------------------------------- ingest / run
@app.get("/api/uploads", dependencies=[Depends(auth)])
def uploads():
    d = ws().root / "uploads"
    return [{"name": p.name, "size": p.stat().st_size} for p in sorted(d.iterdir()) if p.is_file()]


@app.post("/api/uploads", dependencies=[Depends(auth)])
async def upload(files: list[UploadFile] = File(...), reset: bool = False):
    if reset:
        ws().clear_uploads()
    saved = []
    for f in files:
        data = await f.read()
        p = ws().add_upload(f.filename or "upload.bin", data)
        saved.append({"name": p.name, "size": len(data)})
    return saved


@app.delete("/api/uploads", dependencies=[Depends(auth)])
def clear_uploads():
    ws().clear_uploads()
    return []


@app.post("/api/run", dependencies=[Depends(auth)])
def run(req: RunRequest):
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
    try:
        st = ws().run(src)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return summary_of(st)


def summary_of(st: dict) -> dict:
    return {"run_id": st["run_id"], "time": st["time"], "tool_version": st["tool_version"], "timings": st["timings"],
            "counts": st["ingest"]["counts"], "rationalization": st["estate"]["rationalization"],
            "review_summary": st["review_summary"], "objects": len(st["objects"]), "findings": len(st["findings"]),
            "entities": len(st["model"]["entities"]), "aggregates": len(st["aggregates"]["plans"]),
            "semantic_views": sum(1 for o in st["objects"] if o["object_type"] == "semantic view"),
            "products": len(st["products"]), "validation": st["validation"], "diff": st["diff"]}


@app.get("/api/summary", dependencies=[Depends(auth)])
def summary():
    return summary_of(state())


@app.get("/api/ingest", dependencies=[Depends(auth)])
def ingest():
    return state()["ingest"]


@app.get("/api/estate", dependencies=[Depends(auth)])
def estate():
    return state()["estate"]


@app.get("/api/model", dependencies=[Depends(auth)])
def model():
    return state()["model"]


@app.get("/api/logical-model", dependencies=[Depends(auth)])
def logical_model():
    st = state()
    if "logical" not in st:
        raise HTTPException(404, "logical model not in this run - re-run the pipeline")
    return st["logical"]


@app.get("/api/lineage", dependencies=[Depends(auth)])
def lineage():
    state()
    p = ws().root / "lineage_index.json"
    if not p.exists():
        raise HTTPException(404, "lineage not in this run - re-run the pipeline")
    return FileResponse(p, media_type="application/json")


# --------------------------------------------------------------------------- portfolio pages
@app.get("/api/portfolio", dependencies=[Depends(auth)])
def portfolio():
    state()
    return ws().portfolio_view()


@app.post("/api/portfolio/{report}", dependencies=[Depends(auth)])
def decide_report(report: str, d: ReportDecision):
    return ws().decide_report(report, d.disposition, d.comment, d.target, d.reviewer)


@app.get("/api/kpis", dependencies=[Depends(auth)])
def kpis():
    state()
    return ws().kpi_view()


@app.post("/api/kpis/{group_id}", dependencies=[Depends(auth)])
def decide_kpi(group_id: str, d: KpiDecision):
    return ws().decide_kpi(group_id, d.variant, d.comment, d.reviewer)


@app.get("/api/sources", dependencies=[Depends(auth)])
def sources():
    state()
    return ws().sources_view()


@app.post("/api/sources/{table_id:path}", dependencies=[Depends(auth)])
def decide_source(table_id: str, d: SourceDecision):
    return ws().decide_source(table_id, d.scope, d.comment, d.reviewer)


@app.get("/api/products-view", dependencies=[Depends(auth)])
def products_view():
    state()
    return ws().view("products") | {"pending_rerun": ws().decisions_pending()}


@app.post("/api/rerun", dependencies=[Depends(auth)])
def rerun():
    """Re-run the pipeline on the uploaded bundle so steward decisions reach the design."""
    try:
        return summary_of(ws().run(None))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/findings", dependencies=[Depends(auth)])
def findings():
    st = state()
    return {"findings": st["findings"], "numbers_that_change": st["numbers_that_change"], "validation": st["validation"]}


@app.patch("/api/findings/{finding_id}", dependencies=[Depends(auth)])
def update_finding(finding_id: str, u: FindingUpdate):
    return ws().update_finding(finding_id, owner=u.owner, status=u.status)


# --------------------------------------------------------------------------- design review
@app.get("/api/objects", dependencies=[Depends(auth)])
def objects(layer: Optional[str] = None):
    st = state()
    out = [{k: v for k, v in o.items() if k not in ("edited_ddl",)} | {"edited": bool(o.get("edited_ddl"))}
           for o in st["objects"] if not layer or o["layer"] == layer]
    return {"objects": out, "summary": st["review_summary"]}


@app.get("/api/objects/{object_id:path}", dependencies=[Depends(auth)])
def object_detail(object_id: str):
    st = state()
    o = next((x for x in st["objects"] if x["id"] == object_id), None)
    if o is None:
        raise HTTPException(404, "unknown object")
    ddl = (ws().output / o["file"]).read_text(encoding="utf-8")
    return o | {"ddl": ddl}


@app.post("/api/objects/{object_id:path}/review", dependencies=[Depends(auth)])
def review(object_id: str, r: ReviewRequest):
    return ws().review(object_id, r.action, reviewer=r.reviewer, comment=r.comment, ddl=r.ddl,
                       acknowledge_low_confidence=r.acknowledge_low_confidence)


@app.post("/api/approve-all", dependencies=[Depends(auth)])
def approve_all():
    return ws().auto_approve()


@app.get("/api/suggestions", dependencies=[Depends(auth)])
def suggestions():
    return sorted(ws().suggestions().values(), key=lambda s: s["target"])


@app.post("/api/suggestions/{sug_id}", dependencies=[Depends(auth)])
def decide(sug_id: str, d: SuggestionDecision):
    return ws().decide_suggestion(sug_id, d.status, d.description, d.synonyms)


@app.get("/api/aggregates", dependencies=[Depends(auth)])
def aggregates():
    return state()["aggregates"]


@app.get("/api/products", dependencies=[Depends(auth)])
def products():
    return state()["products"]


@app.get("/api/diff", dependencies=[Depends(auth)])
def diff():
    return state()["diff"]


# --------------------------------------------------------------------------- deploy & validate
@app.get("/api/deploy", dependencies=[Depends(auth)])
def deploy_status():
    st = state()
    return {"deploy": st.get("deploy"), "parity": st.get("parity"), "review_summary": st["review_summary"],
            "environment": os.environ.get("SEMLIFT_ENV", "development"), "settings": ws().settings()}


@app.post("/api/deploy", dependencies=[Depends(auth)])
def deploy(req: DeployRequest):
    # The UI only ever writes a Git branch; execution against Snowflake happens in CI (FR-13).
    return ws().deploy(branch=req.branch, push=req.push, remote=req.remote)


@app.post("/api/parity", dependencies=[Depends(auth)])
def parity():
    return ws().run_parity()


# --------------------------------------------------------------------------- downloads
def _safe(rel: str) -> Path:
    out = ws().output.resolve()
    p = (out / rel).resolve()
    if not str(p).startswith(str(out) + os.sep) or not p.is_file():
        raise HTTPException(404, "file not found")
    return p


@app.get("/api/files", dependencies=[Depends(auth)])
def files():
    return state()["files"]


@app.get("/api/files/{rel:path}", dependencies=[Depends(auth)])
def file(rel: str):
    p = _safe(rel)
    if p.suffix in (".xlsx",):
        return FileResponse(p, filename=p.name)
    return PlainTextResponse(p.read_text(encoding="utf-8"))


@app.get("/api/download/package", dependencies=[Depends(auth)])
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


@app.get("/api/download/workbook", dependencies=[Depends(auth)])
def download_workbook():
    return FileResponse(_safe("design_workbook.xlsx"), filename="design_workbook.xlsx")


@app.get("/api/download/findings", dependencies=[Depends(auth)])
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
        return {"app": "SemLift", "version": __version__, "ui": "not built - run `npm run build` in ui/", "docs": "/docs"}
