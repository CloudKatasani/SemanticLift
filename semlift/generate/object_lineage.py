"""Object-level lineage for every generated platform object (Object lineage screen).

For each target object: where it comes from (source tables, Cognos FM / report items, upstream objects),
which Cognos reports use it (with their rationalization disposition) and which semantic-layer objects
(aggregates, semantic views, data-product outputs, listings) it feeds.
"""
from __future__ import annotations

from collections import defaultdict

from ..design.model import Design
from ..model import MetaGraph, TargetObject

LAYER_TITLE = {"setup": "Setup", "ref": "Reference", "sec": "Security", "core": "Core model", "agg": "Aggregate",
               "sem": "Semantic view", "dp": "Data product", "meta": "Metadata"}
SEMANTIC_LAYERS = ("agg", "sem", "dp")
LIVE = ("Keep", "Review")


def build_object_lineage(g: MetaGraph, d: Design, objects: list[TargetObject]) -> dict:
    disp = g.analysis.get("report_disposition", {})
    by_id = {o.id: o for o in objects}
    deps = {o.id: [x for x in o.depends_on if x in by_id and by_id[x].layer != "setup"] for o in objects}
    users: dict[str, list[str]] = defaultdict(list)
    for oid, ds in deps.items():
        for x in ds:
            users[x].append(oid)

    # direct report usage ------------------------------------------------------------------
    reports: dict[str, set] = defaultdict(set)
    items: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))   # object -> Cognos item -> reports
    for ri in g.report_items:
        if not ri.resolved_entity:
            continue
        ref = f"{ri.resolved_entity}.{ri.ref_item}"
        hit = d.ref_to_column.get(ref)
        if hit:
            reports[hit[0]].add(ri.report)
            items[hit[0]][ref].add(ri.report)
    for coll in (d.aggregates, d.semantic_views):
        for oid, x in coll.items():
            for cid in x.clusters:
                if cid in g.clusters:
                    reports[oid].update(g.clusters[cid].members)
    # policies / reference tables inherit from the objects that use them; outputs from what they read
    for o in objects:
        if o.layer in ("sec", "ref"):
            for u in users.get(o.id, []):
                reports[o.id].update(reports.get(u, ()))
    for o in sorted(objects, key=lambda o: o.order):
        if o.layer == "dp" and o.object_type != "share + internal listing":
            for x in deps[o.id]:
                reports[o.id].update(reports.get(x, ()))
    for key, p in d.products.items():
        listing = f"{p.schema}.LISTING"
        if listing in by_id:
            for x in list(p.semantic_views) + list(p.outputs):
                reports[listing].update(reports.get(x, ()))
                if x not in deps[listing]:
                    deps[listing].append(x)
                    users[x].append(listing)

    def closure(start: str, nxt: dict) -> list[str]:
        seen, q = set(), [start]
        while q:
            cur = q.pop()
            for n in nxt.get(cur, []):
                if n not in seen:
                    seen.add(n)
                    q.append(n)
        return sorted(seen)

    def sources_of(oid: str) -> list[dict]:
        t = d.tables.get(oid)
        if t is None:
            return []
        out = []
        for s in [t.source] + [u.split("|")[0] for u in t.union_sources] + [j.table for j in t.joins if not j.table.startswith(("REF.", "CORE."))]:
            if s and s not in {x["table"] for x in out}:
                out.append({"table": s, "system": t.source_system, "role": "primary" if s == t.source else "joined"})
        return out

    rows = []
    for o in sorted(objects, key=lambda o: o.order):
        if o.layer == "setup":
            continue
        reps = sorted(reports.get(o.id, ()))
        counts = {k: sum(1 for r in reps if disp.get(r, {}).get("disposition") == k) for k in ("Keep", "Review", "Consolidate", "Retire")}
        down = closure(o.id, users)
        up = closure(o.id, deps)
        t = d.tables.get(o.id)
        rows.append({
            "id": o.id, "layer": o.layer, "layer_title": LAYER_TITLE.get(o.layer, o.layer), "type": o.object_type,
            "domain": o.domain, "product": o.product, "status": o.status, "confidence": o.confidence,
            "comment": o.comment, "rules": o.rule_ids,
            "upstream": deps[o.id], "upstream_all": up,
            "downstream": sorted(users.get(o.id, [])),
            "feeds": [x for x in down if by_id[x].layer in SEMANTIC_LAYERS],
            "sources": sources_of(o.id),
            "cognos": sorted(({"item": k, "reports": len(v)} for k, v in items.get(o.id, {}).items()), key=lambda x: x["item"])
                      or [{"item": c, "reports": None} for c in (t.cognos_source if t else [])][:40],
            "reports": reps, "report_counts": counts,
            "live_reports": counts["Keep"] + counts["Review"],
        })
    layers = defaultdict(int)
    for r in rows:
        layers[r["layer"]] += 1
    summary = {"objects": len(rows), "by_layer": dict(layers),
               "with_reports": sum(1 for r in rows if r["reports"]),
               "with_live_reports": sum(1 for r in rows if r["live_reports"]),
               "feeding_semantic": sum(1 for r in rows if r["feeds"]),
               "without_reports": [r["id"] for r in rows if not r["reports"]]}
    used = sorted({r for row in rows for r in row["reports"]})
    report_info = {r: {"package": disp.get(r, {}).get("package") or g.reports[r].package,
                       "disposition": disp.get(r, {}).get("disposition", ""),
                       "redirect_to": disp.get(r, {}).get("redirect_to")} for r in used}
    return {"summary": summary, "objects": rows, "reports": report_info}
