"""Report portfolio rationalization (Keep / Retire / Review / Consolidate) and the inventory of
databases, schemas and tables/views used by in-scope reports.

Recommendation rules (deterministic, thresholds in ``cfg['rationalization']``):

R1  Retire       every copy in the duplicate group lacks demand (0 runs/day or no run in the look-back window)
R2  Consolidate  archive / community copy of a live report -> redirect to the canonical report
R3  Review       live canonical report with a reason to look before migrating: filter defects, totals that will
                 change (F6), a KPI definition other than the approved one, low or stale usage, duplicate items
R4  Consolidate  live canonical report whose KPIs are a subset of another live report's KPIs in the same package
                 and whose dimensions overlap >= ``consolidate_dim_jaccard`` -> merge into that report
R5  Keep         everything else

Steward decisions (``cfg['_decisions']['reports']``) override the recommendation.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .. import expr as cx
from ..model import MetaGraph
from ..util import jaccard, snake_upper
from .rationalize import as_of

DISPOSITIONS = ("Keep", "Review", "Consolidate", "Retire")
RULES = [
    {"id": "R1", "disposition": "Retire", "rule": "Every copy in the duplicate group lacks demand: 0 runs/day or no run in the look-back window."},
    {"id": "R2", "disposition": "Consolidate", "rule": "Archive / community copy of a live report: redirect users, bookmarks and schedules to the canonical report."},
    {"id": "R3", "disposition": "Review", "rule": "Live report needing a decision first: filter defect, totals that change pending a KPI rule, "
                                                   "a non-approved KPI definition, low or stale usage, duplicate items."},
    {"id": "R4", "disposition": "Consolidate", "rule": "Common KPIs: all of its KPIs exist in another live report of the same package "
                                                        "and the dimensions overlap at or above the threshold; merge into that report."},
    {"id": "R5", "disposition": "Keep", "rule": "Distinct report intent in demand; migrate onto the semantic view."},
]


def resolve_targets(recs: dict) -> None:
    """Point every Consolidate at the report that finally survives (copies of a consolidated report follow it)."""
    for rec in recs.values():
        if rec["disposition"] != "Consolidate" or not rec.get("target"):
            continue
        seen, tgt = {rec["report"]}, rec["target"]
        while tgt in recs and recs[tgt]["disposition"] == "Consolidate" and recs[tgt].get("target") and tgt not in seen:
            seen.add(tgt)
            tgt = recs[tgt]["target"]
        if tgt != rec["target"]:
            rec["reasons"].append(f"{rec['target']} itself consolidates, so redirect to {tgt}.")
            rec["target"] = tgt


def physical_of(g: MetaGraph, entity: str, item: str) -> list[dict]:
    """Where a Cognos item physically lives: FM data source table/column when known, else inferred."""
    obj = g.item(entity, item)
    out = []
    if obj is not None:
        node, _ = cx.try_parse(obj.expression) if (obj.origin == "FM" and obj.expression) else (None, None)
        for r in (cx.refs(node) if node is not None else []):
            if len(r.parts) == 3 and r.parts[1] in g.source_objects:
                so = g.source_objects[r.parts[1]]
                out.append({"system": so.system, "schema": so.schema, "table": so.table, "column": r.parts[2],
                            "object_type": "view" if so.sql and not so.sql.upper().startswith("SELECT * FROM") else "table",
                            "basis": "FM physical layer", "confirmed": True})
        if not out and obj.physical_column and obj.source_object in g.source_objects:
            so = g.source_objects[obj.source_object]
            out.append({"system": so.system, "schema": so.schema, "table": so.table, "column": obj.physical_column,
                        "object_type": "table", "basis": "matched to FM physical column", "confirmed": True})
    if not out:
        out.append({"system": "", "schema": "", "table": snake_upper(entity), "column": snake_upper(item),
                    "object_type": "table", "basis": "inferred from report usage", "confirmed": False})
    return out


def _kpi_reasons(catalog: dict) -> tuple[dict, dict]:
    """Review reasons and informational flags per report from the KPI groups and steward decisions."""
    review, flags = defaultdict(list), defaultdict(list)
    kpis = {k["id"]: k for k in catalog["kpis"]}
    for grp in catalog["groups"]:
        chosen = grp.get("approved_variant")
        ch = next((v for v in grp["variants"] if v["id"] == chosen), None) if chosen else None
        rec = next((v for v in grp["variants"] if v.get("recommended")), None)
        for v in grp["variants"]:
            label = kpis.get(v["kpi"], {}).get("label", v["kpi"])
            for rep in v["reports"]:
                if grp["kind"] == "aggregation":
                    if ch is None and rec and v["id"] != rec["id"]:
                        review[rep].append(f"Totals will change: {label} is {v['aggregation']} in the report but "
                                           f"{rec['aggregation']} in the semantic layer — approve the rule on Common KPIs.")
                    elif ch is not None and v["id"] != ch["id"]:
                        flags[rep].append(f"{label}: approved rule is {ch['aggregation']}; this report's totals change "
                                          f"from {v['aggregation']} (tell the report owner).")
                elif ch is not None and v["id"] != ch["id"]:
                    review[rep].append(
                        f"KPI definition: uses {v['kpi']} for '{grp['title']}', approved definition is {ch['kpi']}."
                        if grp["kind"] == "concept" else
                        f"KPI definition: {label} filtered by {v['filter']}; approved rule is {ch['filter']}.")
                elif ch is None and len(grp["variants"]) > 1:
                    flags[rep].append(f"'{grp['title']}' has {len(grp['variants'])} competing definitions (not yet approved).")
    return review, flags


def _system_for(g: MetaGraph, phys: dict, package: str) -> tuple[str, str]:
    if phys["system"]:
        ss = g.source_systems.get(phys["system"])
        return phys["system"], ss.vendor if ss else ""
    p = g.packages.get(package)
    ss = g.source_systems.get(p.source_system) if p else None
    return (ss.database, ss.vendor) if ss else ("(unmapped)", "")


def rationalize_reports(g: MetaGraph, cfg: dict, catalog: dict | None = None) -> dict:
    rc = cfg["rationalization"]
    ref_date = as_of(g, cfg)
    window_start = ref_date - dt.timedelta(days=int(rc["lookback_days"]))
    stale_start = ref_date - dt.timedelta(days=int(rc.get("review_stale_days", 90)))
    min_review_runs = float(rc.get("review_min_runs_per_day", 1))
    thr = float(rc.get("consolidate_dim_jaccard", 0.6))
    review_kpi, flag_kpi = _kpi_reasons(catalog or {"kpis": [], "groups": []})
    dup_items = defaultdict(set)
    meas, dims, filters = defaultdict(set), defaultdict(set), defaultdict(list)
    for ri in g.report_items:
        if ri.duplicate_name:
            dup_items[ri.report].add(ri.name)
        if ri.resolved_entity:
            (meas if ri.resolved_kind == "measure" else dims)[ri.report].add(f"{ri.resolved_entity}.{ri.ref_item}")
    for f in g.report_filters:
        filters[f.report].append({"expression": f.expression.replace(f"[{g.reports[f.report].package}].", ""),
                                  "defect": f.defect, "reason": f.defect_reason})

    def weight(r):
        return (r.runs_per_day or 0) * (r.avg_duration or 0)

    recs: dict[str, dict] = {}
    live_canon = []
    for cid, c in sorted(g.clusters.items()):
        canon = g.reports[c.canonical]
        for name in c.members:
            r = g.reports[name]
            rec = {"report": name, "package": r.package, "type": r.type, "folder": r.folder, "cluster": cid,
                   "canonical": c.canonical, "similarity": r.similarity, "runs_per_day": r.runs_per_day,
                   "last_run": r.last_run, "avg_duration": r.avg_duration, "weighted_demand": round(weight(r), 2),
                   "description": r.description, "kpis": sorted(meas[name]), "dimensions": sorted(dims[name]),
                   "filters": filters[name], "reasons": [], "flags": [], "target": None, "rule": "", "overlap": None}
            if c.disposition == "Retire":
                rec["recommendation"], rec["rule"] = "Retire", "R1"
                rec["reasons"].append(
                    f"No demand in any copy of group {cid}: {c.runs_per_day:g} runs/day across {len(c.members)} copies and no "
                    f"run since {window_start.isoformat()} ({rc['lookback_days']}-day window)."
                    if c.runs_per_day == 0 else
                    f"No copy of group {cid} ran since {window_start.isoformat()} ({rc['lookback_days']}-day window); "
                    f"last run {r.last_run or 'never'}.")
                if r.folder != "Active":
                    rec["reasons"].append(f"{r.folder} copy of {c.canonical} ({r.similarity:g}% similar).")
            elif name != c.canonical:
                rec["recommendation"], rec["rule"], rec["target"] = "Consolidate", "R2", c.canonical
                same = sorted(meas[name] | dims[name]) == sorted(meas[c.canonical] | dims[c.canonical])
                extra = sorted((meas[name] | dims[name]) - (meas[c.canonical] | dims[c.canonical]))
                rec["reasons"].append(
                    f"{r.folder} copy of {c.canonical} ({r.similarity:g}% similar); "
                    + ("identical KPIs and columns." if same else
                       f"extra columns {', '.join(extra) or 'none'} are carried into the canonical semantic contract.")
                    + f" Redirect {r.runs_per_day or 0:g} runs/day and bookmarks/schedules to {c.canonical}.")
            else:
                live_canon.append(name)
                rec["recommendation"], rec["rule"] = "Keep", "R5"
            recs[name] = rec

    # R3 review triggers on live canonical reports (usage is judged on the whole duplicate group)
    for name in live_canon:
        r, rec = g.reports[name], recs[name]
        c = g.clusters[r.cluster]
        grp_runs = sum(g.reports[m].runs_per_day or 0 for m in c.members)
        grp_last = max((g.reports[m].last_run or "") for m in c.members) or None
        rec["group_runs_per_day"], rec["group_last_run"] = grp_runs, grp_last
        rs = []
        own_defects = [f for f in rec["filters"] if f["defect"]]
        if own_defects:
            rs.append("Filter defect: " + "; ".join(f"{f['expression']} — {f['reason']}" for f in own_defects))
        rs += review_kpi.get(name, [])
        rec["flags"] += flag_kpi.get(name, [])
        if grp_runs < min_review_runs:
            rs.append(f"Low usage: {grp_runs:g} runs/day across all {len(c.members)} copies (< {min_review_runs:g}); "
                      "confirm the audience still needs it.")
        if grp_last and dt.date.fromisoformat(grp_last) < stale_start:
            rs.append(f"Stale: no copy has run since {grp_last} (older than {rc.get('review_stale_days', 90)} days).")
        if dup_items.get(name):
            rs.append(f"Duplicate data item names: {', '.join(sorted(dup_items[name]))}.")
        if rs:
            rec["recommendation"], rec["rule"] = "Review", "R3"
            rec["reasons"] += rs

    # R4 consolidation by common KPIs among live canonical reports
    by_pkg = defaultdict(list)
    for n in live_canon:
        by_pkg[g.reports[n].package].append(n)
    target_of = {}
    for pkg, names in by_pkg.items():
        for a in sorted(names):
            ma, da = meas[a], dims[a]
            if not ma:
                continue
            best = None
            for b in names:
                if b == a or not ma <= meas[b]:
                    continue
                j = jaccard(da, dims[b])
                if j < thr:
                    continue
                ra, rb = g.reports[a], g.reports[b]
                if ma == meas[b] and (weight(rb), b) < (weight(ra), a):
                    continue           # equal KPI sets: the busier report is the survivor
                key = (j, len(meas[b]), weight(rb), b)
                if best is None or key > best[0]:
                    best = (key, b, j)
            if best:
                target_of[a] = (best[1], best[2])
    for a in sorted(target_of):
        tgt, j = target_of[a]
        seen = {a}
        while tgt in target_of and tgt not in seen:     # follow chains to the surviving report
            seen.add(tgt)
            tgt = target_of[tgt][0]
        if tgt == a:
            continue
        rec = recs[a]
        rec["overlap"] = {"target": tgt, "kpis_shared": len(meas[a] & meas[tgt]), "kpis_total": len(meas[a]),
                          "target_kpis": len(meas[tgt]), "dimension_jaccard": round(jaccard(dims[a], dims[tgt]), 2),
                          "extra_dimensions": sorted(dims[a] - dims[tgt])}
        text = (f"All {len(meas[a])} KPIs ({', '.join(sorted(m.split('.')[1] for m in meas[a]))}) are also in {tgt} "
                f"({len(meas[tgt])} KPIs); dimension overlap {rec['overlap']['dimension_jaccard']:.0%}"
                + (f"; add {', '.join(rec['overlap']['extra_dimensions'])} to {tgt}" if rec["overlap"]["extra_dimensions"] else "")
                + ".")
        if rec["recommendation"] == "Review":
            rec["flags"].append(f"Consolidation candidate: {text}")
        else:
            rec["recommendation"], rec["rule"], rec["target"] = "Consolidate", "R4", tgt
            rec["reasons"].append(f"Common KPIs: {text}")
    for name in live_canon:
        rec = recs[name]
        if rec["recommendation"] == "Keep":
            absorbed = sorted(n for n, x in recs.items() if x.get("target") == name and x["rule"] == "R4")
            rec["reasons"].append(
                f"Distinct report intent in demand: {rec['group_runs_per_day']:g} runs/day across {len(g.clusters[rec['cluster']].members)} copies, "
                f"last run {rec['group_last_run']}"
                + (f"; absorbs {', '.join(absorbed)} (common KPIs)" if absorbed else "")
                + f"; {len(rec['kpis'])} KPIs, {len(rec['dimensions'])} dimensions.")

    # steward decisions
    dec = cfg.get("_decisions", {}).get("reports", {})
    for name, rec in recs.items():
        d = dec.get(name)
        rec["decision"] = d
        rec["disposition"] = d["disposition"] if d and d.get("disposition") in DISPOSITIONS else rec["recommendation"]
        if d and d.get("target"):
            rec["target"] = d["target"]
    resolve_targets(recs)
    for rec in recs.values():
        rec["redirect_to"] = rec["target"] if rec["disposition"] == "Consolidate" else None
    summary = defaultdict(int)
    for rec in recs.values():
        summary[rec["disposition"]] += 1
    by_package = defaultdict(lambda: defaultdict(int))
    for rec in recs.values():
        by_package[rec["package"]][rec["disposition"]] += 1
    g.analysis["report_disposition"] = recs
    return {"reports": [recs[n] for n in sorted(recs)], "summary": dict(summary),
            "by_package": {k: dict(v) for k, v in sorted(by_package.items())},
            "rules": RULES,
            "thresholds": {"lookback_days": rc["lookback_days"], "review_min_runs_per_day": min_review_runs,
                           "review_stale_days": rc.get("review_stale_days", 90), "consolidate_dim_jaccard": thr,
                           "as_of": ref_date.isoformat()}}


def source_inventory(g: MetaGraph, cfg: dict, design=None) -> dict:
    """Databases -> schemas -> tables/views (with columns) used by Keep and Review reports."""
    recs = g.analysis.get("report_disposition", {})
    in_scope = {n: r["disposition"] for n, r in recs.items() if r["disposition"] in ("Keep", "Review")}
    tables: dict[tuple, dict] = {}
    for ri in g.report_items:
        if ri.report not in in_scope or not ri.resolved_entity:
            continue
        disp = in_scope[ri.report]
        rep = g.reports[ri.report]
        for ph in physical_of(g, ri.resolved_entity, ri.ref_item):
            db, vendor = _system_for(g, ph, rep.package)
            schema = ph["schema"] or "(to confirm)"
            key = (db, schema, ph["table"])
            t = tables.get(key)
            if t is None:
                p = g.packages.get(rep.package)
                t = tables[key] = {
                    "id": f"{db}.{schema}.{ph['table']}", "database": db, "vendor": vendor, "schema": schema,
                    "table": ph["table"], "object_type": ph["object_type"], "basis": ph["basis"], "confirmed": ph["confirmed"],
                    "entities": set(), "packages": set(), "systems_of_record": set(), "columns": {},
                    "keep_reports": set(), "review_reports": set(), "kpis": set(), "landed": set(), "core": set()}
            t["entities"].add(ri.resolved_entity)
            t["packages"].add(rep.package)
            p = g.packages.get(rep.package)
            if p and p.source_system:
                t["systems_of_record"].add(p.source_system)
            col = t["columns"].setdefault(ph["column"], {"column": ph["column"], "item": f"{ri.resolved_entity}.{ri.ref_item}",
                                                         "kind": ri.resolved_kind, "keep": set(), "review": set()})
            (col["keep"] if disp == "Keep" else col["review"]).add(ri.report)
            (t["keep_reports"] if disp == "Keep" else t["review_reports"]).add(ri.report)
            if ri.resolved_kind == "measure":
                t["kpis"].add(f"{ri.resolved_entity}.{ri.ref_item}")
            if design is not None:
                ref = f"{ri.resolved_entity}.{ri.ref_item}"
                if ref in design.ref_to_column:
                    tid, c = design.ref_to_column[ref]
                    t["core"].add(tid)
                    cd = design.tables[tid].col(c)
                    if cd is not None and cd.source_column:
                        t["landed"].add(cd.source_column.rsplit(".", 1)[0])
    dec = cfg.get("_decisions", {}).get("sources", {})
    out = []
    for key in sorted(tables):
        t = tables[key]
        review_only = not t["keep_reports"]
        rec = "Review" if review_only else "Include"
        d = dec.get(t["id"])
        out.append({
            **{k: v for k, v in t.items() if not isinstance(v, (set, dict))},
            "entities": sorted(t["entities"]), "packages": sorted(t["packages"]),
            "systems_of_record": sorted(t["systems_of_record"]), "kpis": sorted(t["kpis"]),
            "landed": sorted(t["landed"]), "core": sorted(t["core"]),
            "keep_reports": sorted(t["keep_reports"]), "review_reports": sorted(t["review_reports"]),
            "columns": [{"column": c["column"], "item": c["item"], "kind": c["kind"], "keep": len(c["keep"]),
                         "review": len(c["review"]), "review_only": not c["keep"]}
                        for c in sorted(t["columns"].values(), key=lambda c: c["column"])],
            "review_only": review_only, "recommendation": rec, "decision": d,
            "scope": d["scope"] if d and d.get("scope") else rec,
        })
    dbs = defaultdict(lambda: {"schemas": set(), "tables": 0, "review_only": 0, "vendor": ""})
    for t in out:
        x = dbs[t["database"]]
        x["schemas"].add(t["schema"])
        x["tables"] += 1
        x["review_only"] += 1 if t["review_only"] else 0
        x["vendor"] = t["vendor"]
    return {"tables": out, "databases": [{"database": k, "vendor": v["vendor"], "schemas": sorted(v["schemas"]),
                                          "tables": v["tables"], "review_only": v["review_only"]} for k, v in sorted(dbs.items())],
            "scope_reports": {"Keep": sum(1 for v in in_scope.values() if v == "Keep"),
                              "Review": sum(1 for v in in_scope.values() if v == "Review")}}
