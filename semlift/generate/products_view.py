"""Data-product view: what moves from the BI semantic layer onto the data platform, per product,
with table-level lineage (source -> CORE -> AGG / SEM -> DP output -> reports served)."""
from __future__ import annotations

from ..design.model import Design
from ..model import MetaGraph


def _logic_rows(g: MetaGraph, d: Design, tables: list[str]) -> list[dict]:
    """Business logic that leaves Cognos: calculations, aggregation rules, prompts, security, constants."""
    rows = []
    for tid in tables:
        t = d.tables[tid]
        for c in t.columns:
            obj = g.item(*c.ref.split(".", 1)) if c.ref else None
            if obj is not None and obj.origin == "FM" and obj.is_calculated:
                rows.append({"kind": "Calculation", "cognos": f"{c.ref} := {obj.expression}",
                             "platform": f"{tid}.{c.name} = {c.expr}", "rule": c.rule or "CORE-04"})
            if c.masking_policy:
                rows.append({"kind": "Column security", "cognos": f"{c.ref or c.name} (objectLevelSecurity / masking / ABAC)",
                             "platform": f"{c.masking_policy} on {tid}.{c.name}", "rule": "SEC-03"})
        if t.row_access_policy:
            pid = t.row_access_policy[0]
            p = d.policies.get(pid)
            rows.append({"kind": "Row security", "cognos": f"{p.cognos_rule}: {p.cognos_source}" if p else pid,
                         "platform": f"{pid} on {tid}({', '.join(t.row_access_policy[1])})", "rule": "SEC-02"})
        for j in t.joins:
            if j.table.startswith("REF."):
                rows.append({"kind": "Hard-coded constant", "cognos": "literal factor in FM calculation",
                             "platform": f"{j.table} joined in {tid} ({j.on})", "rule": "CORE-05"})
    return rows


def build_products_view(g: MetaGraph, d: Design, cfg: dict) -> dict:
    disp = g.analysis.get("report_disposition", {})
    sv_reports: dict[str, set] = {}
    for sid, sv in d.semantic_views.items():
        names = set()
        for cid in sv.clusters:
            for m in g.clusters[cid].members:
                if disp.get(m, {}).get("disposition") in ("Keep", "Review"):
                    names.add(m)
        sv_reports[sid] = names
    products = []
    for key, p in sorted(d.products.items(), key=lambda x: (x[0] == "ENTERPRISE", x[0])):
        svs = []
        for sid in p.semantic_views:
            sv = d.semantic_views[sid]
            svs.append({
                "id": sid, "name": sv.name, "description": sv.description, "stub": sv.stub, "confidence": sv.confidence,
                "tables": [{"alias": t.alias, "table": t.table} for t in sv.tables],
                "relationships": [f"{r.from_alias}({', '.join(r.from_columns)}) → {r.to_alias}" for r in sv.relationships],
                "dimensions": [{"name": f.name, "table": f.alias, "expr": f.expr, "synonyms": f.synonyms[:4],
                                "sample_values": f.sample_values[:6]} for f in sv.dimensions],
                "metrics": [{"name": f.name, "table": f.alias, "expr": f.expr, "aggregation": f.aggregation or "",
                             "ref": f.ref, "comment": f.comment} for f in sv.metrics],
                "facts": len(sv.facts), "default_filters": sv.default_filters,
                "verified_queries": [{"question": q.question, "sql": q.semantic_sql} for q in sv.verified_queries],
                "reports_served": sorted(sv_reports.get(sid, [])),
            })
        logic = _logic_rows(g, d, sorted(p.core_tables))
        for s_ in svs:
            for m in s_["metrics"]:
                meas = g.measures.get(m["ref"]) if m["ref"] else None
                if m["aggregation"] == "ratio":
                    logic.append({"kind": "Ratio metric", "cognos": f"{m['ref']} := {meas.expression if meas else ''} (regularAggregate=calculated)",
                                  "platform": f"{s_['id']}.{m['table']}.{m['name']} = {m['expr']}", "rule": "SEM-02"})
                elif meas is not None and meas.additivity != "additive":
                    logic.append({"kind": "Aggregation rule", "cognos": f"{m['ref']}: reports apply 'total' (SUM); FM default "
                                                                         f"{meas.regular_aggregate or meas.default_aggregation}",
                                  "platform": f"{s_['id']}.{m['table']}.{m['name']} = {m['expr']}", "rule": "SEM-02 / F6"})
            for f in s_["default_filters"]:
                logic.append({"kind": "Prompt", "cognos": f"?{f['parameter']}? (required, default {f['default']})",
                              "platform": f"default filter {f['dimension']} = {f['default']} in {s_['id']} contract", "rule": "SEM-03"})
        product_tables = set(p.core_tables) | {t["table"] for s in svs for t in s["tables"]}
        aggs = [a for a in d.aggregates.values() if a.fact_table in product_tables and a.domain == key]
        outs = [d.outputs[o] for o in p.outputs]
        # table-level lineage graph
        nodes, edges = {}, []

        def node(nid, layer, label, stub=False, extra=None):
            nodes.setdefault(nid, {"id": nid, "layer": layer, "label": label, "stub": stub, **(extra or {})})
            return nid

        def edge(a, b):
            if a and b and (a, b) not in {(e["from"], e["to"]) for e in edges}:
                edges.append({"from": a, "to": b})
        for tid in sorted(product_tables):
            t = d.tables[tid]
            core = node(tid, "core", tid, t.stub, {"kind": t.kind})
            srcs = {t.source} | {u.split("|")[0] for u in t.union_sources}
            for s in sorted(x for x in srcs if x):
                edge(node(s, "source", s, False, {"system": t.source_system}), core)
        for a in aggs:
            an = node(a.id, "agg", a.id, a.stub, {"coverage": a.coverage_pct})
            edge(a.fact_table, an)
            for _al, tid, _on in a.joins:
                if tid in nodes:
                    edge(tid, an)
        for s in svs:
            sn = node(s["id"], "sem", s["id"], s["stub"])
            for t in s["tables"]:
                edge(t["table"], sn)
            for r in s["reports_served"][:40]:
                edge(sn, node(f"report:{r}", "report", r, False, {"disposition": disp.get(r, {}).get("disposition")}))
        for o in outs:
            on = node(o.id, "dp", o.id, o.stub)
            for dep in o.depends_on:
                if dep in nodes:
                    edge(dep, on)
        reports = [x for x in disp.values() if x["package"] == key]
        products.append({
            "key": key, "name": p.name, "slug": p.slug, "schema": p.schema, "domain_code": p.domain_code,
            "owner": p.owner, "steward": p.steward, "classification": p.classification, "retention": p.retention,
            "freshness_sla": p.freshness_sla, "source_systems": p.source_systems, "data_modules": p.data_modules,
            "confidence": p.confidence, "contract": f"contracts/{p.slug}.yaml", "listing": f"{p.schema}.LISTING",
            "default_filters": p.default_filters, "quality_rules": len(p.quality),
            "semantic_views": svs,
            "aggregates": [{"id": a.id, "fact_table": a.fact_table, "grain": a.grain_refs, "implementation": a.implementation,
                            "target_lag": a.target_lag, "coverage_pct": a.coverage_pct, "est_rows": a.est_rows,
                            "credits_per_day": a.credits_per_day, "measures": [m[0] for m in a.measures],
                            "stub": a.stub, "excluded": a.excluded} for a in sorted(aggs, key=lambda a: a.id)],
            "outputs": [{"id": o.id, "columns": o.columns, "depends_on": o.depends_on, "stub": o.stub, "comment": o.comment}
                        for o in outs],
            "core_tables": [{"id": t, "kind": d.tables[t].kind, "stub": d.tables[t].stub,
                             "confidence": d.tables[t].confidence, "source": d.tables[t].source} for t in sorted(p.core_tables)],
            "business_logic": logic,
            "reports": {k: sum(1 for x in reports if x["disposition"] == k) for k in ("Keep", "Review", "Consolidate", "Retire")},
            "lineage": {"nodes": list(nodes.values()), "edges": edges},
        })
    return {"products": products}
