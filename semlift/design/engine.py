"""Stage 4 - design engine: canonical graph -> platform-neutral design + validation (spec 6, 8.3)."""
from __future__ import annotations

from ..model import MetaGraph
from .core import CoreBuilder
from .model import Design
from .security import SecurityBuilder
from .semantic import SemanticBuilder

NON_SUMMABLE = ("semi", "non")


def build_design(g: MetaGraph, cfg: dict) -> Design:
    d = Design()
    CoreBuilder(g, cfg, d).build()
    sec = SecurityBuilder(g, cfg, d)
    sec.build()
    sb = SemanticBuilder(g, cfg, d)
    sb.build_aggregates()
    sb.build_semantic_views()
    sb.build_products()
    sec.build_grants()
    d.issues.extend({"layer": "sec", "unmapped": True, **u} for u in sec.unmapped if u not in
                    [{k: v for k, v in i.items() if k in ("rule", "reason")} for i in d.issues])
    d.tags = ["DOMAIN", "DATA_OWNER", "DATA_CLASSIFICATION", "SENSITIVE", "RETENTION", "ACCESS_GROUP", "ABAC_POLICY"]
    validate(g, cfg, d)
    return d


def validate(g: MetaGraph, cfg: dict, d: Design) -> None:
    """Spec 8.3 validation rules. Results go to g.analysis['validation'] and blocking findings."""
    results = []
    # V1: every active, non-retired report item resolves to exactly one semantic object or has an open finding
    open_objs = {f.object for f in g.findings if f.status == "open"}
    unresolved, multi, total = [], 0, 0
    for ri in g.report_items:
        rep = g.reports[ri.report]
        if rep.folder != "Active" or rep.disposition == "Retire":
            continue
        total += 1
        ref = f"{ri.resolved_entity}.{ri.ref_item}"
        targets = d.ref_to_semantic.get(ref, [])
        if not targets and ref not in open_objs and ri.resolved_entity not in open_objs:
            unresolved.append(f"{ri.report}:{ri.name}")
        if len(targets) > 1:
            multi += 1
    results.append({"rule": "V1", "title": "Active report items resolve to a semantic object or carry a finding",
                    "passed": not unresolved, "detail": f"{total} items checked; {len(unresolved)} without target or finding; "
                                                        f"{multi} items exposed in more than one semantic view (shared dimensions)",
                    "failures": unresolved[:50]})
    # V2: no metric sums a semi/non-additive measure
    bad = []
    for sv in d.semantic_views.values():
        for m in sv.metrics:
            if not m.ref or not m.expr.upper().startswith("SUM("):
                continue
            meas = g.measures.get(m.ref)
            if meas is not None and meas.additivity in NON_SUMMABLE and m.aggregation != "ratio":
                bad.append(f"{sv.name}.{m.name}")
    for a in d.aggregates.values():
        ft = d.tables[a.fact_table]
        for out, sql, kind in a.measures:
            c = ft.col(out)
            if c is not None and kind == "sum" and c.additivity in NON_SUMMABLE:
                bad.append(f"{a.name}.{out}")
    results.append({"rule": "V2", "title": "No generated metric sums a semi- or non-additive measure",
                    "passed": not bad, "detail": f"{len(bad)} violations", "failures": bad})
    # V3: every Cognos security rule maps to a platform policy
    mapped = {p.cognos_rule for p in d.policies.values()}
    unmapped = []
    for r in sorted(g.security_rules.values(), key=lambda r: r.name):
        if r.type == "row" and r.name not in mapped:
            unmapped.append(r.name)
        elif r.type == "mask" and r.name not in mapped:
            unmapped.append(r.name)
        elif r.type == "column_grant" and not any(row[3] == r.name for row in d.sec_tables.get("SEC.MAP_ROLE_GRANT", {}).get("rows", [])):
            unmapped.append(r.name)
        elif r.type == "namespace" and not any(x["rule"] == r.name for x in d.sec_tables.get("SEC.GRANTS", {}).get("rows", [])):
            unmapped.append(r.name)
    for i in d.issues:
        if i.get("unmapped") and i["rule"] not in unmapped:
            unmapped.append(i["rule"])
    results.append({"rule": "V3", "title": "Every Cognos security rule maps to a platform policy (unmapped rules block deployment)",
                    "passed": not unmapped, "detail": f"{len(g.security_rules)} rules; {len(unmapped)} unmapped",
                    "failures": unmapped})
    for u in unmapped:
        g.add_finding("F16", f"Security rule {u} not mapped to a platform policy", severity="high", obj=u,
                      evidence=next((i.get("reason", "") for i in d.issues if i.get("rule") == u), ""),
                      resolution="Blocks deployment until mapped", blocking=True)
    for i in d.issues:
        if i.get("layer") == "sec" and not i.get("unmapped"):
            g.add_finding("F16", f"Security rule {i['rule']}: {i['issue']}", severity="medium", obj=i["rule"],
                          evidence="Policy generated; attach once the target column exists", resolution="Map target column")
    # V4: owner, classification tag, comment on every object
    missing = [t.id for t in d.tables.values() if not (t.tags.get("DATA_OWNER") and t.tags.get("DATA_CLASSIFICATION") and t.comment)]
    missing += [sv.id for sv in d.semantic_views.values() if not sv.description]
    results.append({"rule": "V4", "title": "Every target object has an owner, a classification tag and a comment",
                    "passed": not missing, "detail": f"{len(missing)} objects missing governance metadata", "failures": missing})
    # V5 is executed by the compile checker (generated SQL must compile before approval)
    results.append({"rule": "V5", "title": "Generated SQL must compile (EXPLAIN) before approval",
                    "passed": None, "detail": "Evaluated per object by the compile checker", "failures": []})
    g.analysis["validation"] = results
