"""Column-level source-to-target lineage index used by the Lineage screen.

One entry per CORE column, carrying the full chain from spec section 1:
report column -> Cognos data item -> FM query item -> source column -> new platform object,
extended downstream to semantic views, aggregates and data-product outputs.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .. import expr as cx
from ..design.model import Design
from ..model import MetaGraph


def _fm_physical(g: MetaGraph, obj) -> list[str]:
    """Cognos-side physical columns (e.g. ENERGY_DW.BILLING.BILL_AMOUNT) referenced by an FM item."""
    if obj is None or obj.origin != "FM" or not obj.expression:
        return []
    node, _ = cx.try_parse(obj.expression)
    out = []
    for r in (cx.refs(node) if node is not None else []):
        if len(r.parts) == 3:
            so = g.source_objects.get(r.parts[1])
            if so:
                col = f"{so.schema}.{so.table}.{r.parts[2]}"
                if col not in out:
                    out.append(col)
    return out


def build_lineage_index(g: MetaGraph, d: Design) -> dict:
    # downstream consumers per CORE column -------------------------------------------------
    agg_use: dict[str, list[dict]] = defaultdict(list)
    for aid, a in sorted(d.aggregates.items()):
        alias_table = {al: tid for al, tid, _ in a.joins}
        alias_table["f"] = a.fact_table
        for al, col, out in a.group_columns:
            agg_use[f"{alias_table.get(al, '')}.{col}"].append({"object": aid, "column": out, "role": "group by",
                                                                 "stub": a.stub})
        for out, sql, kind in a.measures:
            for col in re.findall(r"f\.([A-Z0-9_]+)", sql):
                agg_use[f"{a.fact_table}.{col}"].append({"object": aid, "column": out, "role": kind, "stub": a.stub})
    out_use: dict[str, list[dict]] = defaultdict(list)
    for oid, o in sorted(d.outputs.items()):
        for dep in o.depends_on:
            if dep in d.aggregates:
                a = d.aggregates[dep]
                for key, uses in agg_use.items():
                    for u in uses:
                        if u["object"] == dep and u["column"] in o.columns:
                            out_use[key].append({"object": oid, "column": u["column"], "via": dep, "stub": o.stub})
            elif dep in d.tables:
                for c in d.tables[dep].columns:
                    if c.name in o.columns:
                        out_use[f"{dep}.{c.name}"].append({"object": oid, "column": c.name, "via": dep, "stub": o.stub})
    sem_use: dict[str, list[dict]] = defaultdict(list)
    for sid, sv in sorted(d.semantic_views.items()):
        alias_table = {t.alias: t.table for t in sv.tables}
        facts = {(f.alias, f.name): f.expr for f in sv.facts}
        for kind, fields in (("dimension", sv.dimensions), ("fact", sv.facts)):
            for f in fields:
                sem_use[f"{alias_table[f.alias]}.{f.expr}"].append(
                    {"object": sid, "field": f"{f.alias}.{f.name}", "kind": kind, "stub": sv.stub})
        for m in sv.metrics:
            for al, fname in re.findall(r"([a-z0-9_]+)\.([a-z0-9_]+)", m.expr):
                col = facts.get((al, fname))
                if col and al in alias_table:
                    sem_use[f"{alias_table[al]}.{col}"].append(
                        {"object": sid, "field": f"{m.alias}.{m.name}", "kind": f"metric ({m.aggregation or 'sum'})",
                         "expr": m.expr, "stub": sv.stub})

    # upstream: report columns per canonical ref -------------------------------------------
    rep_use: dict[str, dict[str, dict]] = defaultdict(dict)
    for ri in sorted(g.report_items, key=lambda r: (r.report, r.name)):
        if not ri.resolved_entity:
            continue
        ref = f"{ri.resolved_entity}.{ri.ref_item}"
        rep = g.reports[ri.report]
        e = rep_use[ref].setdefault(ri.report, {"report": ri.report, "package": rep.package, "folder": rep.folder,
                                                "disposition": rep.disposition, "columns": [], "aggregate": ri.aggregate})
        if ri.name not in e["columns"]:
            e["columns"].append(ri.name)
    filt_use: dict[str, set] = defaultdict(set)
    for f in g.report_filters:
        if f.ref_subject:
            filt_use[f"{f.ref_subject}.{f.ref_item}"].add(f.report)

    columns = []
    for tid, t in sorted(d.tables.items()):
        for c in t.columns:
            key = f"{tid}.{c.name}"
            obj = g.item(*c.ref.split(".", 1)) if c.ref else None
            reports = sorted(rep_use.get(c.ref, {}).values(), key=lambda r: r["report"]) if c.ref else []
            columns.append({
                "id": key, "table": tid, "column": c.name, "kind": c.kind, "data_type": c.data_type,
                "domain": t.domain, "table_stub": t.stub, "todo": c.todo, "confidence": c.confidence,
                "transform": c.expr, "masking_policy": c.masking_policy,
                "ref": c.ref,
                "cognos": None if obj is None else {
                    "item": c.ref, "origin": obj.origin, "expression": obj.expression,
                    "fm_item": f"Business Layer.{c.ref}" if obj.origin == "FM" else "",
                    "physical": _fm_physical(g, obj), "labels": list(obj.labels),
                    "aggregation": getattr(obj, "default_aggregation", ""), "confidence": obj.confidence},
                "sources": [s.strip() for s in c.source_column.split(",") if s.strip()],
                "semantic": sem_use.get(key, []), "aggregates": agg_use.get(key, []), "outputs": out_use.get(key, []),
                "reports": reports, "filter_reports": sorted(filt_use.get(c.ref, set())) if c.ref else [],
            })
    # gaps: report items whose canonical item has no CORE column ----------------------------
    mapped = {c["ref"] for c in columns if c["ref"]}
    gaps = []
    for ref, reps in sorted(rep_use.items()):
        if ref not in mapped:
            gaps.append({"ref": ref, "reports": len(reps)})
    unresolved = [{"report": ri.report, "column": ri.name, "expression": ri.expression}
                  for ri in g.report_items if not ri.resolved_entity]
    active = [ri for ri in g.report_items if g.reports[ri.report].folder == "Active"
              and g.reports[ri.report].disposition != "Retire"]
    to_sem = sum(1 for ri in active if d.ref_to_semantic.get(f"{ri.resolved_entity}.{ri.ref_item}"))
    to_core = sum(1 for ri in active if f"{ri.resolved_entity}.{ri.ref_item}" in d.ref_to_column)
    summary = {
        "core_columns": len(columns),
        "confirmed_source": sum(1 for c in columns if c["sources"] and not c["todo"]),
        "todo_source": sum(1 for c in columns if c["todo"]),
        "with_cognos_origin": sum(1 for c in columns if c["cognos"]),
        "fm_origin": sum(1 for c in columns if c["cognos"] and c["cognos"]["origin"] == "FM"),
        "consumed": sum(1 for c in columns if c["semantic"] or c["aggregates"] or c["outputs"]),
        "active_report_items": len(active), "active_items_to_core": to_core, "active_items_to_semantic": to_sem,
        "gaps": len(gaps), "unresolved_items": len(unresolved),
    }
    sources = sorted({s.rsplit(".", 1)[0] for c in columns for s in c["sources"] if s.count(".") >= 2})
    reports = sorted({r["report"] for c in columns for r in c["reports"]})
    return {"summary": summary, "columns": columns, "gaps": gaps, "unresolved": unresolved[:200],
            "source_tables": sources, "reports": reports,
            "tables": sorted(d.tables), "semantic_views": sorted(d.semantic_views)}
