"""Stage 1 - ingest: unpack the bundle, detect adapters, parse every file into the MetaGraph.

Adapters never talk to each other; cross-file reconciliation happens in ``finalize``.
"""
from __future__ import annotations

from pathlib import Path

from ..model import IngestFile, MetaGraph, Package, Provenance, Report
from . import fm as fmmod
from .reports import parse_reports
from .sheets import parse_catalog, parse_mapping, parse_usage
from .unpack import detect_adapter, unpack


def ingest_bundle(source: str | Path, work_dir: str | Path, cfg: dict,
                  extra_sources: list[str | Path] | None = None) -> MetaGraph:
    root = unpack(source, work_dir)
    if extra_sources:
        import shutil
        for i, extra in enumerate(extra_sources):
            dest = root / f"_extra_{i}"
            dest.mkdir()
            p = Path(extra)
            if p.is_dir():
                shutil.copytree(p, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(p, dest / p.name)
    return ingest_folder(root, cfg)


def ingest_folder(root: Path, cfg: dict) -> MetaGraph:
    g = MetaGraph()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    fm_models: dict[str, list[tuple[Path, str]]] = {}
    sec_files, param_files, ds_files, ns_files, cpfs = [], [], [], [], []
    deferred = []
    for p in files:
        rel = p.relative_to(root).as_posix().replace(".zip.d/", ".zip/")
        adapter, detail = detect_adapter(p)
        rec = IngestFile(path=rel, adapter=adapter or "-", size=p.stat().st_size)
        g.files.append(rec)
        if not adapter:
            rec.status = "rejected"
            rec.warnings.append(detail)
            continue
        try:
            if adapter == "FM-PROJ" and detail == "cpf":
                cpfs.append((p, rel, rec))
            elif adapter == "FM-PROJ":
                fm_models.setdefault(str(p.parent if p.parent.name != "model" else p.parent.parent), []).append((p, rel, rec))
            elif adapter == "FM-SEC":
                sec_files.append((p, rel, rec))
            elif adapter == "FM-PARAM":
                param_files.append((p, rel, rec))
            elif adapter == "FM-DS":
                ds_files.append((p, rel, rec))
            elif adapter == "FM-NS":
                ns_files.append((p, rel, rec))
            elif adapter == "FM-PUB":
                rec.records = 1
            else:
                deferred.append((adapter, p, rel, rec))
        except Exception as e:  # pragma: no cover - defensive
            rec.status = "rejected"
            rec.warnings.append(str(e))

    # ---- FM projects: prefer package.xml (published) over model.xml, diff both
    for _folder, models in sorted(fm_models.items()):
        parsed = []
        for p, rel, rec in sorted(models, key=lambda x: x[1]):
            try:
                fm = fmmod.parse_fm_model(p, rel)
                rec.records = sum(len(ns["querySubjects"]) for ns in fm["namespaces"].values())
                parsed.append((p.name.lower(), fm))
            except Exception as e:
                rec.status = "rejected"
                rec.warnings.append(f"FM parse error: {e}")
        if not parsed:
            continue
        by = dict(parsed)
        primary = by.get("package.xml") or parsed[0][1]
        if "package.xml" in by and "model.xml" in by:
            diffs = fmmod.diff_models(by["model.xml"], by["package.xml"])
            g.analysis.setdefault("fm_drift", {})[primary["package_name"]] = diffs
        fmmod.load_fm_into_graph(g, primary, cfg)
        pkg = primary["package_name"]
        g.packages.setdefault(pkg, Package(name=pkg, prov=Provenance(primary["file"], "/project")))
        g.packages[pkg].fm_project = pkg
        for dm in primary["data_modules"]:
            if dm not in g.packages[pkg].data_modules:
                g.packages[pkg].data_modules.append(dm)
        g.analysis.setdefault("model_security", {})[pkg] = primary["security"]
        for pm in primary["parameter_maps"]:
            for prm in pm["parameters"]:
                from ..model import Parameter
                g.parameters.setdefault(prm["name"], Parameter(
                    name=prm["name"], data_type=prm.get("dataType", "string"), default=prm.get("defaultValue"),
                    multi_select=prm.get("multiSelect") == "true", origin="FM-MODEL",
                    prov=Provenance(primary["file"], pm["xpath"])))

    for p, rel, rec in cpfs:
        cpf = fmmod.parse_cpf(p, rel)
        g.analysis.setdefault("fm_projects", []).append(cpf)
        rec.records = len(cpf["files"])
    for p, rel, rec in ns_files:
        ns = fmmod.parse_namespace_summary(p, rel)
        g.analysis.setdefault("ns_summaries", []).append(ns)
        rec.records = len(ns["querySubjects"])
    for p, rel, rec in ds_files:
        ds = fmmod.parse_datasource(p, rel)
        g.analysis.setdefault("datasources", []).append(ds)
        sysname = ds["catalog"] or ds["schema"] or ds["name"]
        ss = g.source_systems.get(sysname)
        if ss:
            ss.connection = ds["url"]
            ss.vendor = ss.vendor or ds["vendor"]
        rec.records = len(ds["tables"])
    for p, rel, rec in sorted(param_files, key=lambda x: x[1]):
        params = fmmod.parse_parameter_map(p, rel)
        for prm in params:
            g.parameters[prm.name] = prm          # file definition wins over model-embedded
        rec.records = len(params)

    # ---- security: dedicated files win by default; embedded model block kept for drift
    file_rules = []
    for p, rel, rec in sorted(sec_files, key=lambda x: x[1]):
        blk = fmmod.parse_security_file(p, rel)
        rules = blk["row"] + blk["ols"] + blk["abac"] + blk["namespace"]
        file_rules.extend(rules)
        rec.records = len(rules)
    model_rules = []
    for blk in g.analysis.get("model_security", {}).values():
        model_rules.extend(blk["row"] + blk["ols"] + blk["abac"] + blk.get("namespace", []))
    prefer_files = cfg["security"]["precedence"] == "security_files"
    primary_rules, secondary = (file_rules, model_rules) if (prefer_files and file_rules) else (model_rules, file_rules)
    for r in primary_rules:
        g.security_rules[f"{r.type}:{r.name}"] = r
    # Rules only present in the secondary source are still carried (never silently dropped)
    def cover_key(r):
        return (r.type, r.name) if r.type in ("abac", "row", "namespace") else (r.type, r.target_entity, r.target_item)
    covered = {cover_key(r) for r in primary_rules}
    for r in secondary:
        if cover_key(r) not in covered and f"{r.type}:{r.name}" not in g.security_rules:
            g.security_rules[f"{r.type}:{r.name}"] = r
    g.analysis["security_secondary"] = secondary

    # ---- reports, usage, mapping, catalog
    for adapter, p, rel, rec in deferred:
        try:
            if adapter == "RPT":
                rec.records = parse_reports(p, rel, g)
            elif adapter == "USAGE":
                rec.records = parse_usage(p, rel, g)
            elif adapter == "MAP":
                rec.records = parse_mapping(p, rel, g)
            elif adapter == "SRC-CAT":
                rec.records = parse_catalog(p, rel, g)
        except Exception as e:
            rec.status = "rejected"
            rec.warnings.append(f"{adapter} parse error: {e}")

    finalize(g, cfg)
    return g


def finalize(g: MetaGraph, cfg: dict) -> None:
    """Join usage to reports (by name, then path), register packages, raw schema routing."""
    by_path = {r.path: r for r in g.reports.values() if r.path}
    matched_usage = 0
    orphans_usage = []
    for row in g.usage_rows:
        r = g.reports.get(row["report_name"]) or by_path.get(row["report_path"])
        if r is None:
            orphans_usage.append(row["report_name"])
            continue
        r.runs_per_day = row["runs_per_day"]
        r.last_run = row["last_run_date"]
        r.avg_duration = row["avg_duration_min"]
        r.column_count = int(row["column_count"]) if row["column_count"] is not None else None
        # raw report specifications carry no folder, path or duplicate group: take them from the usage sheet
        r.folder = r.folder or str(row.get("folder_category") or "").strip()
        r.path = r.path or row["report_path"]
        r.package = r.package or str(row.get("package") or "").strip()
        if not r.dup_group and row.get("duplicate_group_id"):
            r.dup_group = str(row["duplicate_group_id"]).strip()
        if r.similarity is None and row.get("similarity_score") is not None:
            r.similarity = row["similarity_score"]
        r.usage_matched = True
        matched_usage += 1
    g.analysis["usage_join"] = {
        "usage_rows": len(g.usage_rows), "matched": matched_usage, "usage_orphans": orphans_usage,
        "reports_without_usage": sorted(r.name for r in g.reports.values() if not r.usage_matched),
    }
    for r in g.reports.values():
        if r.package and r.package not in g.packages:
            g.packages[r.package] = Package(name=r.package)
    overrides = cfg["target"]["raw_schema_overrides"]
    prefix = cfg["target"]["raw_schema_prefix"]
    for ss in g.source_systems.values():
        if not ss.raw_schema:
            stem = ss.database
            for suf in ("_PROD", "_DB"):
                if stem.endswith(suf):
                    stem = stem[: -len(suf)]
            ss.raw_schema = overrides.get(ss.database) or f"{prefix}{stem}"
    if not g.export_date and g.usage_rows:
        g.export_date = max((r["last_run_date"] or "") for r in g.usage_rows) or None


__all__ = ["ingest_bundle", "ingest_folder", "Report"]
