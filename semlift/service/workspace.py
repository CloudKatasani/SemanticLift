"""Workspace: one migration project on disk. Runs the pipeline, writes the versioned output package,
persists review decisions / finding state / suggestions across re-runs, diffs runs, deploys via Git."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from .. import __version__
from ..config import deep_merge, load_config
from ..generate import artifacts
from ..generate.workbook import write_workbook
from ..model import TargetObject
from ..pipeline import RunResult, run
from ..util import stable_hash
from . import compile as compiler
from .cicd import ci_files
from .llm import draft_suggestions
from .repository import meta_mirror, save_graph

REVIEW_STATES = ("approved", "rejected", "edited")


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class ReviewError(ValueError):
    pass


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in ("uploads", "runs", "review", "output", "deploy"):
            (self.root / sub).mkdir(exist_ok=True)
        self.last: RunResult | None = None

    # ------------------------------------------------------------ paths
    @property
    def output(self) -> Path:
        return self.root / "output"

    @property
    def decisions_path(self) -> Path:
        return self.root / "review" / "decisions.json"

    @property
    def findings_path(self) -> Path:
        return self.root / "review" / "findings_state.json"

    @property
    def suggestions_path(self) -> Path:
        return self.root / "review" / "suggestions.json"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    @property
    def config_path(self) -> Path:
        return self.root / "config.yaml"

    def decisions(self) -> dict:
        return _read_json(self.decisions_path, {})

    def suggestions(self) -> dict:
        return _read_json(self.suggestions_path, {})

    def state(self) -> dict:
        return _read_json(self.state_path, {})

    def settings(self) -> dict:
        return _read_json(self.root / "settings.json", {})

    def save_settings(self, data: dict) -> None:
        cur = self.settings()
        cur.update(data)
        _write_json(self.root / "settings.json", cur)

    # ------------------------------------------------------------ upload / config
    def add_upload(self, filename: str, data: bytes) -> Path:
        name = Path(filename).name
        if not name:
            raise ValueError("empty filename")
        dest = self.root / "uploads" / name
        dest.write_bytes(data)
        return dest

    def clear_uploads(self) -> None:
        shutil.rmtree(self.root / "uploads")
        (self.root / "uploads").mkdir()

    def set_config(self, base: str | Path | None, overrides: dict | None = None) -> dict:
        cfg = load_config(base, overrides)
        self.config_path.write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
        return cfg

    def config(self) -> dict:
        if self.config_path.exists():
            return load_config(self.config_path)
        return load_config(None)

    # ------------------------------------------------------------ run
    def run(self, source: str | Path | None = None, *, live_compile: bool = False, extra_sources=None) -> dict:
        src = Path(source) if source else self.root / "uploads"
        if src.is_dir() and not any(src.iterdir()):
            raise ValueError("No input files uploaded")
        cfg = self.config()
        decisions = self.portfolio_decisions()
        res = run(src, self.root / "work", cfg, extra_sources=extra_sources, suggestions=self.suggestions(),
                  decisions=decisions)
        res.compile_results = compiler.check_all(res.objects, live=live_compile)
        prev = self._previous_objects()
        run_id = self._next_run_id(res)
        self._apply_decisions(res)
        self._apply_finding_state(res)
        files = self._write_package(res)
        diff = self._diff(prev, res.objects)
        run_dir = self.root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_json(run_dir / "objects.json", {o.id: {"hash": o.meta["generated_hash"], "layer": o.layer,
                                                    "type": o.object_type, "status": o.status} for o in res.objects})
        _write_json(run_dir / "diff.json", diff)
        _write_json(run_dir / "run.json", {"run_id": run_id, "time": _now(), "timings": res.timings,
                                           "tool_version": __version__, "files": len(files)})
        try:
            save_graph(res.graph, self.root / "semlift.db", run_id)
        except Exception as e:  # pragma: no cover - repository is best-effort for the UI
            res.graph.analysis["repository_error"] = str(e)
        sug = draft_suggestions(res.graph, res.design, cfg, self.suggestions())
        _write_json(self.suggestions_path, sug)
        self.last = res
        from ..generate.lineage import build_lineage_index
        _write_json(self.root / "lineage_index.json", build_lineage_index(res.graph, res.design))
        from ..generate.products_view import build_products_view
        _write_json(self.root / "views" / "portfolio.json", res.graph.analysis["portfolio"])
        _write_json(self.root / "views" / "kpis.json", res.graph.analysis["kpi_catalog"])
        _write_json(self.root / "views" / "sources.json", res.graph.analysis["source_inventory"])
        _write_json(self.root / "views" / "products.json", build_products_view(res.graph, res.design, cfg))
        _write_json(self.root / "views" / "applied_decisions.json", {"hash": stable_hash(decisions, 16)})
        state = self._build_state(res, run_id, diff, files)
        _write_json(self.state_path, state)
        return state

    def _next_run_id(self, res: RunResult) -> str:
        n = len([p for p in (self.root / "runs").iterdir() if p.is_dir()]) + 1
        h = stable_hash(sorted((o.id, o.ddl) for o in res.objects), 8)
        return f"{n:04d}-{h}"

    def _previous_objects(self) -> dict:
        runs = sorted(p for p in (self.root / "runs").iterdir() if p.is_dir())
        return _read_json(runs[-1] / "objects.json", {}) if runs else {}

    @staticmethod
    def _diff(prev: dict, objects: list[TargetObject]) -> dict:
        cur = {o.id: o.meta["generated_hash"] for o in objects}
        if not prev:
            return {"baseline": True, "added": sorted(cur), "changed": [], "removed": [], "unchanged": 0}
        return {"baseline": False,
                "added": sorted(k for k in cur if k not in prev),
                "changed": sorted(k for k in cur if k in prev and prev[k]["hash"] != cur[k]),
                "removed": sorted(k for k in prev if k not in cur),
                "unchanged": sum(1 for k in cur if k in prev and prev[k]["hash"] == cur[k])}

    # ------------------------------------------------------------ review
    def _apply_decisions(self, res: RunResult) -> None:
        dec = self.decisions()
        for o in res.objects:
            h = stable_hash(o.ddl)
            o.meta["generated_hash"] = h
            o.meta["compile"] = res.compile_results.get(o.id, {})
            d = dec.get(o.id)
            if not d:
                continue
            o.meta["review"] = {k: d.get(k) for k in ("status", "reviewer", "comment", "time", "acknowledged_low_confidence")}
            if d.get("edited_ddl"):
                o.meta["edited_ddl"] = d["edited_ddl"]
                o.meta["edit_compile"] = d.get("edit_compile", {})
            if d.get("base_hash") != h and d["status"] in ("approved", "edited"):
                o.meta["review"]["changed_since_review"] = True
                o.status = "stub" if o.status == "stub" else "proposed"
                continue
            if d["status"] == "approved":
                o.status = "approved"
            elif d["status"] == "rejected":
                o.status = "rejected"
            elif d["status"] == "edited":
                o.status = "edited"

    def review(self, object_id: str, action: str, *, reviewer: str = "steward", comment: str = "",
               ddl: str | None = None, acknowledge_low_confidence: bool = False) -> dict:
        state = self.state()
        obj = next((o for o in state.get("objects", []) if o["id"] == object_id), None)
        if obj is None:
            raise ReviewError(f"unknown object {object_id}")
        dec = self.decisions()
        cur = dec.get(object_id, {})
        entry = {"base_hash": obj["generated_hash"], "reviewer": reviewer, "comment": comment, "time": _now(),
                 "edited_ddl": cur.get("edited_ddl"), "edit_compile": cur.get("edit_compile")}
        if action == "reset":
            dec.pop(object_id, None)
            _write_json(self.decisions_path, dec)
            return self._refresh_object_state(object_id, None)
        if action == "edit":
            if not ddl or not ddl.strip():
                raise ReviewError("edited DDL is empty")
            tmp = TargetObject(id=object_id, layer=obj["layer"], object_type=obj["object_type"], schema="", name="", ddl=ddl)
            chk = compiler.offline_check(tmp)
            entry.update({"status": "edited", "edited_ddl": ddl, "edit_compile": chk})
        elif action == "approve":
            chk = entry.get("edit_compile") or obj.get("compile") or {}
            if chk.get("status") == "failed":
                raise ReviewError(f"cannot approve: SQL does not compile ({chk.get('message')})")
            thr = self.config()["confidence"]["auto_approve_min"]
            if obj["confidence"] < thr and not acknowledge_low_confidence:
                raise ReviewError(f"confidence {obj['confidence']:.2f} is below {thr}: inferred objects cannot be "
                                  "auto-approved; a steward must acknowledge the TODO source mappings")
            entry.update({"status": "approved", "acknowledged_low_confidence": acknowledge_low_confidence})
        elif action == "reject":
            entry["status"] = "rejected"
        else:
            raise ReviewError(f"unknown action {action}")
        dec[object_id] = entry
        _write_json(self.decisions_path, dec)
        return self._refresh_object_state(object_id, entry)

    def auto_approve(self, reviewer: str = "auto") -> dict:
        """Approve every proposed object that meets the confidence threshold and compiles."""
        state = self.state()
        thr = self.config()["confidence"]["auto_approve_min"]
        n = 0
        for o in state.get("objects", []):
            if o["status"] == "proposed" and o["confidence"] >= thr and o.get("compile", {}).get("status") != "failed":
                self.review(o["id"], "approve", reviewer=reviewer, comment="auto-approved (confidence >= threshold)")
                n += 1
        return {"approved": n}

    def _refresh_object_state(self, object_id: str, entry: dict | None) -> dict:
        state = self.state()
        for o in state.get("objects", []):
            if o["id"] != object_id:
                continue
            if entry is None:
                o["status"] = o["generated_status"]
                o["review"] = None
                o["edited_ddl"] = None
            else:
                o["review"] = {k: entry.get(k) for k in ("status", "reviewer", "comment", "time", "acknowledged_low_confidence")}
                o["status"] = entry["status"] if entry["status"] in REVIEW_STATES else o["generated_status"]
                o["edited_ddl"] = entry.get("edited_ddl")
                o["edit_compile"] = entry.get("edit_compile")
            state["review_summary"] = self._review_summary(state["objects"])
            _write_json(self.state_path, state)
            return o
        raise ReviewError(f"unknown object {object_id}")

    @staticmethod
    def _review_summary(objects: list[dict]) -> dict:
        out: dict[str, int] = {}
        for o in objects:
            out[o["status"]] = out.get(o["status"], 0) + 1
        return dict(sorted(out.items()))

    # ------------------------------------------------------------ findings & suggestions
    def _apply_finding_state(self, res: RunResult) -> None:
        st = _read_json(self.findings_path, {})
        for f in res.graph.findings:
            s = st.get(f"{f.code}:{f.object}:{f.title}")
            if s:
                f.owner = s.get("owner", f.owner)
                f.status = s.get("status", f.status)

    def update_finding(self, finding_id: str, owner: str | None = None, status: str | None = None) -> dict:
        state = self.state()
        f = next((x for x in state.get("findings", []) if x["id"] == finding_id), None)
        if f is None:
            raise ReviewError(f"unknown finding {finding_id}")
        if status and status not in ("open", "accepted", "resolved", "wont_fix"):
            raise ReviewError("invalid status")
        st = _read_json(self.findings_path, {})
        key = f"{f['code']}:{f['object']}:{f['title']}"
        cur = st.get(key, {})
        if owner is not None:
            f["owner"] = cur["owner"] = owner
        if status is not None:
            f["status"] = cur["status"] = status
        st[key] = cur
        _write_json(self.findings_path, st)
        _write_json(self.state_path, state)
        return f

    def decide_suggestion(self, sug_id: str, status: str, description: str | None = None,
                          synonyms: list[str] | None = None) -> dict:
        if status not in ("accepted", "rejected", "suggested"):
            raise ReviewError("invalid status")
        sug = self.suggestions()
        if sug_id not in sug:
            raise ReviewError("unknown suggestion")
        sug[sug_id]["status"] = status
        if description is not None:
            sug[sug_id]["description"] = description
        if synonyms is not None:
            sug[sug_id]["synonyms"] = synonyms
        _write_json(self.suggestions_path, sug)
        return sug[sug_id]

    # ------------------------------------------------------------ package
    def _write_package(self, res: RunResult) -> list[str]:
        g, d, cfg = res.graph, res.design, res.config
        out = self.output
        if out.exists():
            shutil.rmtree(out)
        out.mkdir()
        files: dict[str, str] = {}
        for o in sorted(res.objects, key=lambda o: o.order):
            files[o.meta["file"]] = o.ddl
        files.update(artifacts.semantic_yaml(g, d, cfg))
        files.update(artifacts.databricks_metric_views(g, d, cfg))
        files.update(artifacts.dbt_project(g, d, cfg))
        files.update(artifacts.contracts(g, d, cfg))
        trace = artifacts.trace_rows(g, d)
        files["traceability.csv"] = artifacts.traceability_csv(trace)
        files["lineage.json"] = artifacts.openlineage(g, d, cfg)
        files["findings.md"] = artifacts.findings_md(g, d)
        files.update(artifacts.parity_sql(g, d, cfg))
        files.update(meta_mirror(g))
        manifest = {"tool": f"SemLift {__version__}", "objects": [
            {"id": o.id, "file": o.meta["file"], "layer": o.layer, "type": o.object_type, "status": o.status,
             "confidence": o.confidence, "depends_on": o.depends_on, "hash": o.meta["generated_hash"]}
            for o in sorted(res.objects, key=lambda o: o.order)]}
        files["manifest.json"] = json.dumps(manifest, indent=2)
        files["README.md"] = self._package_readme(res)
        for rel, text in files.items():
            p = out / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        write_workbook(out / "design_workbook.xlsx", g, d, res.objects, trace, self.decisions())
        return sorted(files) + ["design_workbook.xlsx"]

    def _package_readme(self, res: RunResult) -> str:
        g = res.graph
        stubs = sum(o.status == "stub" for o in res.objects)
        return (f"# SemLift design package\n\nGenerated by SemLift {__version__}.\n\n"
                f"- {len(res.objects)} target objects ({stubs} stubs that are never auto-deployed)\n"
                f"- {len(res.design.semantic_views)} semantic views, {len(res.design.aggregates)} aggregates, "
                f"{len(res.design.products)} data products\n- {len(g.findings)} findings (see findings.md)\n\n"
                "| Path | Content |\n| --- | --- |\n"
                "| ddl/<layer>/NNNN_*.sql | One object per file; NNNN is the global dependency order |\n"
                "| semantic/snowflake/*.yaml | Cortex Analyst semantic models |\n"
                "| semantic/databricks/*.yaml | Unity Catalog metric views |\n"
                "| dbt/ | dbt project (models, sources, tests, exposures per report cluster) |\n"
                "| contracts/*.yaml | Data product contracts (ODCS style) |\n"
                "| design_workbook.xlsx | Review workbook for sign-off |\n"
                "| lineage.json / traceability.csv | OpenLineage events and report-column traceability |\n"
                "| findings.md | Findings register |\n| validation/*.sql | Parity queries (Cognos-equivalent vs semantic view) |\n"
                "| meta/ | SEMLIFT_META mirror of the canonical model |\n| manifest.json | Deployment order and hashes |\n")

    # ------------------------------------------------------------ portfolio decisions (pages 1, 3, 4)
    @property
    def portfolio_decisions_path(self) -> Path:
        return self.root / "review" / "portfolio_decisions.json"

    def portfolio_decisions(self) -> dict:
        d = _read_json(self.portfolio_decisions_path, {})
        return {"reports": d.get("reports", {}), "kpis": d.get("kpis", {}), "sources": d.get("sources", {})}

    def _save_portfolio_decisions(self, d: dict) -> None:
        _write_json(self.portfolio_decisions_path, d)

    def view(self, name: str) -> dict:
        v = _read_json(self.root / "views" / f"{name}.json", None)
        if v is None:
            raise ReviewError(f"no {name} view yet - run the pipeline")
        return v

    def decisions_pending(self) -> bool:
        applied = _read_json(self.root / "views" / "applied_decisions.json", {}).get("hash")
        return applied != stable_hash(self.portfolio_decisions(), 16)

    def portfolio_view(self) -> dict:
        v = self.view("portfolio")
        dec = self.portfolio_decisions()["reports"]
        summary: dict[str, int] = {}
        for r in v["reports"]:
            d = dec.get(r["report"])
            r["decision"] = d
            r["disposition"] = d["disposition"] if d else r["recommendation"]
            if d and d.get("target"):
                r["target"] = d["target"]
            summary[r["disposition"]] = summary.get(r["disposition"], 0) + 1
        from ..analyze.portfolio import resolve_targets
        recs = {r["report"]: r for r in v["reports"]}
        resolve_targets(recs)
        v["summary"] = summary
        v["pending_rerun"] = self.decisions_pending()
        return v

    def decide_report(self, report: str, disposition: str | None, comment: str = "", target: str | None = None,
                      reviewer: str = "steward") -> dict:
        from ..analyze.portfolio import DISPOSITIONS
        v = self.view("portfolio")
        if not any(r["report"] == report for r in v["reports"]):
            raise ReviewError(f"unknown report {report}")
        d = self.portfolio_decisions()
        if not disposition:
            d["reports"].pop(report, None)
        else:
            if disposition not in DISPOSITIONS:
                raise ReviewError(f"disposition must be one of {', '.join(DISPOSITIONS)}")
            if disposition == "Consolidate" and target and not any(r["report"] == target for r in v["reports"]):
                raise ReviewError(f"unknown consolidation target {target}")
            d["reports"][report] = {"disposition": disposition, "comment": comment, "target": target,
                                    "reviewer": reviewer, "time": _now()}
        self._save_portfolio_decisions(d)
        return next(r for r in self.portfolio_view()["reports"] if r["report"] == report)

    def kpi_view(self) -> dict:
        v = self.view("kpis")
        dec = self.portfolio_decisions()["kpis"]
        for grp in v["groups"]:
            dd = dec.get(grp["id"])
            grp["decision"] = dd
            grp["approved_variant"] = dd["variant"] if dd else None
            grp["status"] = "approved" if dd else "open"
        v["pending_rerun"] = self.decisions_pending()
        return v

    def decide_kpi(self, group_id: str, variant_id: str | None, comment: str = "", reviewer: str = "steward") -> dict:
        v = self.view("kpis")
        grp = next((x for x in v["groups"] if x["id"] == group_id), None)
        if grp is None:
            raise ReviewError(f"unknown KPI group {group_id}")
        d = self.portfolio_decisions()
        if not variant_id:
            d["kpis"].pop(group_id, None)
        else:
            var = next((x for x in grp["variants"] if x["id"] == variant_id), None)
            if var is None:
                raise ReviewError("unknown variant")
            d["kpis"][group_id] = {"variant": variant_id, "kind": grp["kind"], "kpi": var["kpi"],
                                   "aggregation": var["aggregation"], "filter": var["filter"], "title": grp["title"],
                                   "comment": comment, "reviewer": reviewer, "time": _now()}
        self._save_portfolio_decisions(d)
        return next(x for x in self.kpi_view()["groups"] if x["id"] == group_id)

    def sources_view(self) -> dict:
        v = self.view("sources")
        dec = self.portfolio_decisions()["sources"]
        for t in v["tables"]:
            dd = dec.get(t["id"])
            t["decision"] = dd
            t["scope"] = dd["scope"] if dd else t["recommendation"]
        v["pending_rerun"] = self.decisions_pending()
        return v

    def decide_source(self, table_id: str, scope: str | None, comment: str = "", reviewer: str = "steward") -> dict:
        v = self.view("sources")
        if not any(t["id"] == table_id for t in v["tables"]):
            raise ReviewError(f"unknown table {table_id}")
        if scope and scope not in ("Include", "Exclude", "Review"):
            raise ReviewError("scope must be Include, Exclude or Review")
        d = self.portfolio_decisions()
        if not scope:
            d["sources"].pop(table_id, None)
        else:
            d["sources"][table_id] = {"scope": scope, "comment": comment, "reviewer": reviewer, "time": _now()}
        self._save_portfolio_decisions(d)
        return next(t for t in self.sources_view()["tables"] if t["id"] == table_id)

    # ------------------------------------------------------------ deploy (FR-13)
    def deploy(self, *, branch: str | None = None, remote: str | None = None, push: bool = False,
               author: str = "SemLift <semlift@localhost>") -> dict:
        state = self.state()
        if not state:
            raise ReviewError("run the pipeline first")
        blocking = [f for f in state["findings"] if f.get("blocking") and f["code"] == "F16" and f["status"] == "open"]
        if blocking:
            raise ReviewError(f"deployment blocked by {len(blocking)} unmapped security rule(s): "
                              + ", ".join(f["object"] for f in blocking))
        objs = sorted((o for o in state["objects"] if o["status"] == "approved"), key=lambda o: o["order"])
        if not objs:
            raise ReviewError("no approved objects to deploy")
        approved = {o["id"] for o in objs}
        all_ids = {o["id"] for o in state["objects"]}
        skipped = []
        deployable = []
        for o in objs:
            missing = [dpd for dpd in o["depends_on"] if dpd in all_ids and dpd not in approved]
            if missing:
                skipped.append({"id": o["id"], "reason": f"depends on unapproved {', '.join(missing)}"})
            else:
                deployable.append(o)
        repo = self.root / "deploy" / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        mig = repo / "migrations"
        if mig.exists():
            shutil.rmtree(mig)
        mig.mkdir()
        manifest = {"tool": f"SemLift {__version__}", "run_id": state["run_id"], "objects": []}
        for o in deployable:
            ddl = o.get("edited_ddl") or (self.output / o["file"]).read_text(encoding="utf-8")
            name = f"R__{o['order']:04d}_{Path(o['file']).stem.split('_', 1)[1]}.sql"
            (mig / name).write_text(ddl, encoding="utf-8")
            manifest["objects"].append({"id": o["id"], "file": f"migrations/{name}", "depends_on": o["depends_on"],
                                        "edited": bool(o.get("edited_ddl"))})
        (repo / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for rel, text in ci_files(self.config()["target"]["database"]).items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        os.chmod(repo / "scripts" / "deploy.sh", 0o755)
        branch = branch or f"semlift/design-{state['run_id']}"
        log = []

        def git(*args):
            r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
            log.append({"cmd": "git " + " ".join(args), "rc": r.returncode, "out": (r.stdout + r.stderr).strip()[-2000:]})
            if r.returncode != 0:
                raise ReviewError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
            return r.stdout.strip()

        if not (repo / ".git").exists():
            git("init", "-q", "-b", "main")
        name, _, email = author.partition(" <")
        git("checkout", "-q", "-B", branch)
        git("add", "-A")
        status = git("status", "--porcelain")
        commit = None
        if status:
            git("-c", f"user.name={name}", "-c", f"user.email={email.rstrip('>') or 'semlift@localhost'}", "commit", "-q",
                "-m", f"SemLift: deploy {len(deployable)} approved objects (run {state['run_id']})")
        commit = git("rev-parse", "HEAD")
        pushed = False
        remote = remote or self.settings().get("git_remote")
        if push and remote:
            remotes = git("remote")
            if "origin" not in remotes.split():
                git("remote", "add", "origin", remote)
            git("push", "-u", "origin", branch)
            pushed = True
        result = {"time": _now(), "branch": branch, "commit": commit, "pushed": pushed, "remote": remote or None,
                  "deployed": [o["id"] for o in deployable], "skipped": skipped, "log": log,
                  "repo": str(repo), "note": "Deployment executes in CI (schemachange / Snowflake CLI); the UI never deploys directly."}
        hist = _read_json(self.root / "deploy" / "history.json", [])
        hist.append(result)
        _write_json(self.root / "deploy" / "history.json", hist)
        state["deploy"] = {"last": result, "history": [{k: h[k] for k in ("time", "branch", "commit", "pushed")} for h in hist[-20:]]}
        _write_json(self.state_path, state)
        return result

    # ------------------------------------------------------------ parity (FR-14)
    def run_parity(self) -> dict:
        idx = _read_json(self.output / "validation" / "parity_index.json", [])
        conn = compiler.live_connection()
        results = []
        for item in idx:
            if conn is None:
                results.append({**item, "status": "not_run", "detail": "no Snowflake connection configured (SEMLIFT_SNOWFLAKE_ACCOUNT)"})
                continue
            sql = (self.output / item["file"]).read_text(encoding="utf-8")  # pragma: no cover - live only
            try:  # pragma: no cover
                cur = conn.cursor()
                cur.execute(sql)
                row = cur.fetchone()
                cols = [c[0] for c in cur.description]
                rec = dict(zip(cols, row))
                statuses = [v for k, v in rec.items() if k.upper().startswith("STATUS_")]
                st = "fail" if "FAIL" in statuses else "pass"
                results.append({**item, "status": st, "detail": rec})
            except Exception as e:  # pragma: no cover
                results.append({**item, "status": "error", "detail": str(e)[:300]})
        state = self.state()
        state["parity"] = {"time": _now(), "results": results}
        _write_json(self.state_path, state)
        return state["parity"]

    # ------------------------------------------------------------ logical data model
    @staticmethod
    def _logical_model(res: RunResult) -> dict:
        """Target logical data model: every CORE table with business names, keys and relationships,
        grouped by subject area (semantic view) and by data product."""
        g, d = res.graph, res.design
        tables = []
        for tid, t in sorted(d.tables.items()):
            fk_cols = {c for fk in t.foreign_keys for c in fk.columns}
            cols = []
            for c in t.columns:
                obj = g.item(*c.ref.split(".", 1)) if c.ref else None
                role = ("pk" if c.name in t.primary_key else "fk" if c.name in fk_cols else
                        "sk" if c.kind == "sk" else "measure" if c.kind == "measure" else
                        "derived" if c.kind == "derived" else "attribute")
                cols.append({
                    "name": c.name, "business_name": obj.name if obj is not None else c.name,
                    "role": role, "data_type": c.data_type, "ref": c.ref, "todo": c.todo,
                    "sensitive": bool(c.masking_policy) or c.sensitive, "masking_policy": c.masking_policy,
                    "aggregation": c.default_aggregation, "additivity": c.additivity, "comment": c.comment,
                    "source_column": c.source_column, "confidence": c.confidence,
                    "semantic": d.ref_to_semantic.get(c.ref, []) if c.ref else [],
                })
            tables.append({
                "id": tid, "name": t.name, "kind": t.kind, "entity": t.entity, "domain": t.domain,
                "confidence": t.confidence, "stub": t.stub, "origin": t.origin, "source": t.source,
                "comment": t.comment, "primary_key": t.primary_key, "grain": t.grain,
                "row_access_policy": t.row_access_policy[0] if t.row_access_policy else None,
                "columns": cols,
                "foreign_keys": [{"columns": fk.columns, "ref_table": fk.ref_table, "ref_columns": fk.ref_columns,
                                  "relationship": fk.relationship, "confidence": fk.confidence}
                                 for fk in t.foreign_keys if fk.ref_table in d.tables],
            })
        areas = [{"id": sv.id, "name": sv.name, "domain": sv.domain, "description": sv.description,
                  "tables": [x.table for x in sv.tables], "stub": sv.stub, "confidence": sv.confidence}
                 for sv in sorted(d.semantic_views.values(), key=lambda s: s.name)]
        products = [{"key": p.key, "name": p.name, "tables": p.core_tables} for p in d.products.values()]
        return {"tables": tables, "subject_areas": areas, "products": products}

    # ------------------------------------------------------------ UI state
    def _build_state(self, res: RunResult, run_id: str, diff: dict, files: list[str]) -> dict:
        g, d = res.graph, res.design
        dec_state = self.state()
        objects = []
        for o in sorted(res.objects, key=lambda o: o.order):
            objects.append({
                "id": o.id, "layer": o.layer, "object_type": o.object_type, "schema": o.schema, "name": o.name,
                "domain": o.domain, "status": o.status, "generated_status": "stub" if "STUB        :" in o.ddl else "proposed",
                "confidence": o.confidence, "owner": o.owner, "classification": o.classification, "comment": o.comment,
                "rule_ids": o.rule_ids, "lineage": o.lineage, "depends_on": o.depends_on, "order": o.order,
                "file": o.meta["file"], "generated_hash": o.meta["generated_hash"], "compile": o.meta.get("compile", {}),
                "review": o.meta.get("review"), "edited_ddl": o.meta.get("edited_ddl"), "edit_compile": o.meta.get("edit_compile"),
                "cognos_source": o.cognos_source, "meta": {k: v for k, v in o.meta.items()
                                                           if k not in ("file", "generated_hash", "compile", "review", "edited_ddl", "edit_compile")},
            })
        reps = g.reports
        pk_stats: dict[str, dict] = {}
        for r in reps.values():
            s = pk_stats.setdefault(r.package, {"package": r.package, "reports": 0, "runs_per_day": 0.0, "by_disposition": {},
                                                "by_folder": {}, "dormant": 0, "source_system": "", "fm_model": False})
            s["reports"] += 1
            s["runs_per_day"] += r.runs_per_day or 0
            s["by_disposition"][r.disposition] = s["by_disposition"].get(r.disposition, 0) + 1
            s["by_folder"][r.folder] = s["by_folder"].get(r.folder, 0) + 1
            s["dormant"] += 1 if (r.runs_per_day or 0) == 0 else 0
        for name, s in pk_stats.items():
            p = g.packages.get(name)
            s["source_system"] = p.source_system if p else ""
            s["data_modules"] = p.data_modules if p else []
            refs = [ri for ri in g.report_items if g.reports[ri.report].package == name and ri.resolution]
            s["fm_coverage_pct"] = round(100.0 * sum(ri.resolution == "fm" for ri in refs) / len(refs), 1) if refs else 0.0
            s["fm_model"] = bool(p and p.fm_project)
        # model canvas
        G = nx.Graph()
        for e in g.entities:
            G.add_node(e)
        for r in g.relationships.values():
            G.add_edge(r.from_entity, r.to_entity)
        pos = nx.spring_layout(G, seed=42, k=1.4 / max(1, len(G)) ** 0.5, iterations=200)
        entities = []
        for e in sorted(g.entities.values(), key=lambda e: e.name):
            items = g.entity_items(e.name)
            used_by = sorted({ri.report for ri in g.report_items if ri.resolved_entity == e.name})
            entities.append({
                "name": e.name, "role": e.role, "origin": e.origin, "confidence": e.confidence, "conformed": e.conformed,
                "domain": e.domain, "packages": e.packages, "primary_key": e.primary_key, "grain": e.grain,
                "x": round(float(pos[e.name][0]), 4), "y": round(float(pos[e.name][1]), 4),
                "targets": d.entity_tables.get(e.name, []),
                "attributes": [{"name": a.name, "kind": "measure" if a.__class__.__name__ == "Measure" else "attribute",
                                "data_type": a.data_type, "origin": a.origin, "confidence": a.confidence,
                                "physical_column": a.physical_column, "expression": a.expression,
                                "aggregation": getattr(a, "default_aggregation", ""), "additivity": getattr(a, "additivity", ""),
                                "sensitive": getattr(a, "sensitive", False), "labels": a.labels,
                                "target": "{}.{}".format(*d.ref_to_column[f"{e.name}.{a.name}"]) if f"{e.name}.{a.name}" in d.ref_to_column else "",
                                "semantic": d.ref_to_semantic.get(f"{e.name}.{a.name}", [])}
                               for a in sorted(items, key=lambda a: a.name)],
                "reports": used_by[:200], "report_count": len(used_by),
            })
        rels = [{"name": r.name, "from": r.from_entity, "to": r.to_entity, "cardinality": r.cardinality,
                 "origin": r.origin, "confidence": r.confidence, "keys": r.join_keys} for r in sorted(g.relationships.values(), key=lambda r: r.name)]
        clusters = [{"id": c.id, "package": c.package, "canonical": c.canonical, "members": c.members, "disposition": c.disposition,
                     "runs_per_day": c.runs_per_day, "weighted_demand": c.weighted_demand, "facts": c.facts, "items": len(c.items),
                     "reason": c.reason} for c in sorted(g.clusters.values(), key=lambda c: c.id)]
        reports = [{"name": r.name, "type": r.type, "package": r.package, "folder": r.folder, "cluster": r.cluster,
                    "canonical": r.canonical, "disposition": r.disposition, "runs_per_day": r.runs_per_day,
                    "last_run": r.last_run, "avg_duration": r.avg_duration, "similarity": r.similarity, "defects": r.defects}
                   for r in sorted(reps.values(), key=lambda r: r.name)]
        findings = [{"id": f.id, "code": f.code, "title": f.title, "severity": f.severity, "object": f.object,
                     "evidence": f.evidence, "owner": f.owner, "resolution": f.resolution, "status": f.status,
                     "count": f.count, "blocking": f.blocking} for f in g.findings]
        aggs = [{"id": a.id, "name": a.name, "fact": a.fact, "fact_table": a.fact_table, "grain": a.grain_refs,
                 "implementation": a.implementation, "coverage_pct": a.coverage_pct, "clusters": a.clusters,
                 "est_rows": a.est_rows, "credits_per_day": a.credits_per_day, "target_lag": a.target_lag,
                 "excluded": a.excluded, "stub": a.stub} for a in sorted(d.aggregates.values(), key=lambda a: a.id)]
        prods = [{"key": p.key, "name": p.name, "slug": p.slug, "schema": p.schema, "semantic_views": p.semantic_views,
                  "outputs": p.outputs, "core_tables": p.core_tables, "source_systems": p.source_systems,
                  "confidence": p.confidence, "clusters": p.clusters, "reports": p.reports} for p in d.products.values()]
        rat = g.analysis.get("rationalization", {})
        return {
            "run_id": run_id, "time": _now(), "tool_version": __version__, "timings": res.timings,
            "ingest": {"files": [f.__dict__ for f in g.files], "stated_counts": g.stated_counts,
                       "reconciliation": g.analysis.get("count_reconciliation", []), "usage_join": g.analysis.get("usage_join", {}),
                       "counts": {"reports": len(reps), "report_items": len(g.report_items), "filters": len(g.report_filters),
                                  "packages": len(g.packages), "fm_entities": sum(e.origin == "FM" for e in g.entities.values()),
                                  "parameters": len(g.parameters), "security_rules": len(g.security_rules),
                                  "source_systems": len(g.source_systems)}},
            "estate": {"packages": sorted(pk_stats.values(), key=lambda s: s["package"]), "rationalization": rat,
                       "clusters": clusters, "reports": reports,
                       "dispositions": rat.get("dispositions", {})},
            "model": {"entities": entities, "relationships": rels, "conformed": g.analysis.get("conformed", {}),
                      "join_issues": g.analysis.get("join_issues", []), "splits": g.analysis.get("splits", {}),
                      "outriggers": g.analysis.get("outriggers", {})},
            "findings": findings,
            "objects": objects, "review_summary": self._review_summary(objects),
            "aggregates": {"plans": aggs, "facts": g.analysis.get("aggregate_facts", {})},
            "products": prods,
            "portfolio_summary": g.analysis.get("portfolio", {}).get("summary", {}),
            "logical": self._logical_model(res),
            "validation": g.analysis.get("validation", []),
            "numbers_that_change": g.analysis.get("numbers_that_change", []),
            "diff": diff, "files": files,
            "deploy": dec_state.get("deploy", {"last": None, "history": []}),
            "parity": dec_state.get("parity", {"time": None, "results": []}),
        }
