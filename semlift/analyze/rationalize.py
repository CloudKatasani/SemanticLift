"""Stage 3 - rationalize the report estate into intent clusters (spec 6.2, FR-06)."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..model import IntentCluster, MetaGraph
from ..util import jaccard


def as_of(g: MetaGraph, cfg: dict) -> dt.date:
    v = cfg.get("as_of_date") or g.export_date
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10]) if v else dt.date.today()


def report_refs(g: MetaGraph) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for ri in g.report_items:
        if ri.resolved_entity:
            ref = f"{ri.resolved_entity}.{ri.ref_item}"
            if ref not in out[ri.report]:
                out[ri.report].append(ref)
    return out


def report_filter_sigs(g: MetaGraph) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for f in g.report_filters:
        out[f.report].append(f.expression.split("].", 1)[-1] if "]." in f.expression else f.expression)
    return out


def _group_without_ids(g: MetaGraph, refs: dict, threshold: float) -> dict[str, list[str]]:
    """Fallback clustering when duplicateGroupID is absent: Jaccard on resolved items + filters."""
    fsig = report_filter_sigs(g)
    names = sorted(g.reports)
    groups: dict[str, list[str]] = {}
    assigned: dict[str, str] = {}
    for n in names:
        sig = set(refs.get(n, [])) | {f"F:{x}" for x in fsig.get(n, [])}
        best, best_s = None, 0.0
        for gid, members in groups.items():
            rep = members[0]
            if g.reports[rep].package != g.reports[n].package:
                continue
            s = jaccard(sig, set(refs.get(rep, [])) | {f"F:{x}" for x in fsig.get(rep, [])})
            if s > best_s:
                best, best_s = gid, s
        if best and best_s >= threshold:
            groups[best].append(n)
            assigned[n] = best
        else:
            gid = f"AUTO_{len(groups) + 1:04d}"
            groups[gid] = [n]
            assigned[n] = gid
    for n, gid in assigned.items():
        g.reports[n].dup_group = gid
    return groups


def rationalize(g: MetaGraph, cfg: dict) -> None:
    rc = cfg["rationalization"]
    ref_date = as_of(g, cfg)
    window_start = ref_date - dt.timedelta(days=int(rc["lookback_days"]))
    min_runs = float(rc["min_runs_per_day"])
    refs = report_refs(g)
    defects_by_report: dict[str, list[str]] = defaultdict(list)
    for f in g.report_filters:
        if f.defect:
            defects_by_report[f.report].append(f.defect)

    if all(r.dup_group for r in g.reports.values()):
        groups: dict[str, list[str]] = defaultdict(list)
        for r in sorted(g.reports.values(), key=lambda x: x.name):
            groups[r.dup_group].append(r.name)
    else:
        groups = _group_without_ids(g, refs, rc["similarity_threshold"])

    def ran_in_window(r) -> bool:
        return bool(r.last_run) and dt.date.fromisoformat(r.last_run) >= window_start

    def has_demand(r) -> bool:
        return (r.runs_per_day or 0) > min_runs and ran_in_window(r)

    order = {"Active": 0, "Archive": 1, "Community": 2}
    for gid in sorted(groups):
        members = sorted(groups[gid], key=lambda n: (order.get(g.reports[n].folder, 3), n))
        reps = [g.reports[n] for n in members]
        active = next((r for r in reps if r.folder == "Active"), reps[0])
        canonical = active
        for r in reps:
            if r is active:
                continue
            if (r.runs_per_day or 0) > (active.runs_per_day or 0) and set(refs.get(r.name, [])) > set(refs.get(active.name, [])):
                canonical = r
        retire = not any(has_demand(r) for r in reps)
        items: list[str] = []
        for r in [canonical] + [x for x in reps if x is not canonical]:
            if r is not canonical and r.folder == "Community" and not ran_in_window(r):
                continue
            for ref in refs.get(r.name, []):
                if ref not in items:
                    items.append(ref)
        filters = sorted({f.expression for f in g.report_filters if f.report == canonical.name and not f.defect})
        surviving = [r for r in reps if has_demand(r)]
        weighted = sum((r.runs_per_day or 0) * (r.avg_duration or 0) for r in surviving)
        cl = IntentCluster(
            id=gid, canonical=canonical.name, members=members, package=canonical.package, items=items,
            filters=filters, runs_per_day=sum(r.runs_per_day or 0 for r in reps), weighted_demand=round(weighted, 4),
            disposition="Retire" if retire else "Migrate",
            reason=(f"no member ran in the {rc['lookback_days']}-day window with runs/day > {min_runs:g}"
                    if retire else f"{len(surviving)} member(s) with demand"))
        facts = []
        for ref in items:
            ent = ref.split(".")[0]
            e = g.entities.get(ent)
            if e and e.role == "fact" and ent not in facts:
                facts.append(ent)
        cl.facts = facts
        for f in facts:
            cl.grain_signature[f] = sorted(
                ref for ref in items
                if g.attributes.get(ref) is not None and (ref.split(".")[0] != f or g.attributes[ref].usage != "identifier"))
        g.clusters[gid] = cl
        for r in reps:
            r.cluster = gid
            r.canonical = canonical.name
            r.defects = sorted(set(defects_by_report.get(r.name, [])))
            if retire:
                r.disposition = "Retire"
            elif r is canonical:
                r.disposition = "Defect fix needed" if r.defects else "Migrate"
            else:
                r.disposition = "Merge"
    g.analysis["rationalization"] = {
        "as_of": ref_date.isoformat(), "window_start": window_start.isoformat(),
        "clusters": len(g.clusters), "retired_clusters": sum(c.disposition == "Retire" for c in g.clusters.values()),
        "distinct_active_signatures": len({tuple(sorted(refs.get(r.name, []))) for r in g.reports.values() if r.folder == "Active"}),
        "archive_matches_active": sum(
            1 for c in g.clusters.values()
            if (a := next((m for m in c.members if g.reports[m].folder == "Active"), None))
            and (b := next((m for m in c.members if g.reports[m].folder == "Archive"), None))
            and sorted(refs.get(a, [])) == sorted(refs.get(b, []))),
        "dispositions": dict(sorted(_count(r.disposition for r in g.reports.values()).items())),
    }


def _count(it) -> dict:
    out: dict = defaultdict(int)
    for x in it:
        out[x] += 1
    return out
