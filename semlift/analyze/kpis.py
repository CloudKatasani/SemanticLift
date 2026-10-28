"""KPI catalog, definition variants and common-KPI groups.

A KPI is a measure demanded by reports. Its *definition* is the tuple
(source item / formula, aggregation rule, filter rule). The export gives three
kinds of disagreement, each surfaced as a "common KPI" group a steward resolves:

* ``aggregation`` - reports aggregate a measure differently from its FM/semantic
  default (e.g. SUM of CapacityFactorPct where FM says AVG);
* ``filter``      - the same measure is reported under different filter rules
  (e.g. BillAmount for all bills vs only PaymentStatus = 'Overdue');
* ``concept``     - one business KPI is implemented by different items in
  different packages (configured in ``kpi_concepts`` or same normalized name).

Steward decisions (``cfg['_decisions']['kpis']``) pick the approved variant; the
pipeline applies aggregation choices to the semantic layer and flags reports that
use a non-approved definition for review.
"""
from __future__ import annotations

from collections import defaultdict

from .. import expr as cx
from ..model import MetaGraph
from ..util import snake_upper, stable_hash, title_words

REPORT_AGG = {"total": "SUM", "sum": "SUM", "average": "AVG", "avg": "AVG", "maximum": "MAX", "minimum": "MIN",
              "count": "COUNT", "none": "SUM", "": "SUM", "automatic": "SUM"}
DEFAULT_AGG = {"sum": "SUM", "avg": "AVG", "max": "MAX", "min": "MIN", "count": "COUNT", "ratio": "RATIO"}


def _vid(*parts) -> str:
    return stable_hash("|".join(map(str, parts)), 10)


def _filter_text(expr_text: str) -> str:
    """Human-readable filter rule without the package qualifier."""
    node, _ = cx.try_parse(expr_text)
    if node is None:
        return expr_text
    return cx.to_sql(node, lambda r: ".".join(r.parts[-2:]) if isinstance(r, cx.Ref) else ".".join(r.parts),
                     prompt=lambda p: f"?{p}?", prefer_iff=False)


def apply_kpi_decisions(g: MetaGraph, cfg: dict) -> None:
    """Aggregation decisions override a measure's default aggregation before design (rule KPI-01)."""
    for gid, dec in sorted(cfg.get("_decisions", {}).get("kpis", {}).items()):
        agg = (dec.get("aggregation") or "").lower()
        kpi = dec.get("kpi")
        if dec.get("kind") != "aggregation" or not agg or kpi not in g.measures:
            continue
        m = g.measures[kpi]
        new = {"sum": "sum", "avg": "avg", "max": "max", "min": "min", "count": "count", "ratio": "ratio"}.get(agg)
        if new and new != m.default_aggregation:
            g.analysis.setdefault("kpi_overrides", []).append(
                {"kpi": kpi, "from": m.default_aggregation, "to": new, "additivity": m.additivity,
                 "comment": dec.get("comment") or ""})
            m.default_aggregation = new
            m.rule = f"{m.rule},KPI-01:steward"


def kpi_override_findings(g: MetaGraph) -> None:
    for o in g.analysis.get("kpi_overrides", []):
        g.add_finding("F21", f"{o['kpi']}: steward approved {o['to'].upper()} instead of {o['from'].upper()}",
                      severity="medium" if o["additivity"] != "additive" and o["to"] == "sum" else "info", obj=o["kpi"],
                      evidence=o["comment"] or "decision on the Common KPIs page",
                      resolution="Semantic metric and aggregates follow the approved definition")


def build_kpi_catalog(g: MetaGraph, cfg: dict, design=None) -> dict:
    disp = g.analysis.get("report_disposition", {})
    # per report query: literal (non-prompt) filters and prompt filters
    q_filters: dict[tuple, list] = defaultdict(list)
    for f in g.report_filters:
        q_filters[(f.report, f.query)].append(f)
    kpis: dict[str, dict] = {}
    for ri in sorted(g.report_items, key=lambda r: (r.report, r.name)):
        if ri.resolved_kind != "measure":
            continue
        ref = f"{ri.resolved_entity}.{ri.ref_item}"
        m = g.measures[ref]
        k = kpis.get(ref)
        if k is None:
            e = g.entities[m.entity]
            k = kpis[ref] = {
                "id": ref, "name": m.name, "label": title_words(m.name).title(), "entity": m.entity,
                "domain": e.domain, "packages": [], "origin": m.origin, "confidence": m.confidence,
                "fm_item": f"Business Layer.{ref}" if m.origin == "FM" else "",
                "formula": m.expression if m.origin == "FM" else f"[{m.entity}].[{m.name}] (direct column, inferred)",
                "default_aggregation": DEFAULT_AGG.get(m.default_aggregation, "SUM"), "additivity": m.additivity,
                "unit": m.unit, "rule": m.rule, "is_calculated": m.is_calculated, "description": m.description,
                "reports": [], "variants": {}, "sources": [], "semantic": [],
            }
        rep = g.reports[ri.report]
        if rep.package not in k["packages"]:
            k["packages"].append(rep.package)
        fl = q_filters.get((ri.report, ri.query), [])
        lits = sorted(_filter_text(f.expression) for f in fl if f.literal is not None and not f.defect)
        prompts = sorted(_filter_text(f.expression) for f in fl if f.parameter)
        defects = sorted(f"{_filter_text(f.expression)} ({f.defect.replace('_', ' ')})" for f in fl if f.defect)
        agg = REPORT_AGG.get((ri.aggregate or "").lower(), (ri.aggregate or "SUM").upper())
        filt = " AND ".join(lits) or ""
        vid = _vid(ref, agg, filt)
        v = k["variants"].setdefault(vid, {"id": vid, "kpi": ref, "aggregation": agg, "filter": filt,
                                           "formula": k["formula"], "reports": [], "source": "reports"})
        d = disp.get(rep.name, {})
        v["reports"].append(rep.name)
        k["reports"].append({"report": rep.name, "package": rep.package, "folder": rep.folder,
                             "disposition": d.get("disposition", rep.disposition), "aggregation": agg,
                             "filter": filt, "prompts": prompts, "defects": defects, "variant": vid,
                             "runs_per_day": rep.runs_per_day, "data_item": ri.name})

    # add the semantic-layer default as an explicit candidate definition when no report uses it
    for ref, k in kpis.items():
        default = k["default_aggregation"]
        if not any(v["aggregation"] == default and not v["filter"] for v in k["variants"].values()):
            vid = _vid(ref, default, "")
            k["variants"][vid] = {"id": vid, "kpi": ref, "aggregation": default, "filter": "", "formula": k["formula"],
                                  "reports": [], "source": "FM default" if k["origin"] == "FM" else "rule default"}

    # physical lineage: database / schema / table / column
    from .portfolio import _system_for, physical_of
    for ref, k in kpis.items():
        m = g.measures[ref]
        landed = ""
        if design is not None and ref in design.ref_to_column:
            tid, col = design.ref_to_column[ref]
            c = design.tables[tid].col(col)
            landed = c.source_column if c is not None else ""
        seen = set()
        for pkg in k["packages"]:
            p = g.packages.get(pkg)
            for ph in physical_of(g, m.entity, m.name):
                db, vendor = _system_for(g, ph, pkg)
                key = (db, ph["schema"], ph["table"], ph["column"])
                if key in seen:
                    continue
                seen.add(key)
                k["sources"].append({"database": db, "vendor": vendor, "schema": ph["schema"] or "(to confirm)",
                                     "table": ph["table"], "column": ph["column"], "object_type": ph["object_type"],
                                     "basis": ph["basis"], "confirmed": ph["confirmed"], "landed": landed,
                                     "system_of_record": p.source_system if p else ""})
        if design is not None:
            k["semantic"] = sorted(design.ref_to_semantic.get(ref, []))

    groups = _groups(g, cfg, kpis)
    decisions = cfg.get("_decisions", {}).get("kpis", {})
    for grp in groups:
        dec = decisions.get(grp["id"])
        grp["decision"] = dec
        chosen = dec.get("variant") if dec else None
        grp["approved_variant"] = chosen
        grp["status"] = "approved" if chosen else "open"
    out = []
    for ref in sorted(kpis):
        k = kpis[ref]
        k["variants"] = sorted(k["variants"].values(), key=lambda v: (-len(v["reports"]), v["aggregation"], v["filter"]))
        k["live_reports"] = sum(1 for r in k["reports"] if r["disposition"] != "Retire")
        out.append(k)
    package_systems = {p.name: p.source_system for p in g.packages.values() if p.source_system}
    return {"kpis": out, "groups": groups, "package_systems": package_systems}


def _live(reports: list[dict], names: list[str]) -> int:
    by = {r["report"]: r for r in reports}
    return sum(1 for n in names if by.get(n, {}).get("disposition") != "Retire")


def _groups(g: MetaGraph, cfg: dict, kpis: dict) -> list[dict]:
    groups = []
    for ref, k in sorted(kpis.items()):
        vs = list(k["variants"].values())
        default = k["default_aggregation"]
        aggs = sorted({v["aggregation"] for v in vs})
        if len(aggs) > 1:
            variants = []
            for a in aggs:
                names = sorted({n for v in vs if v["aggregation"] == a for n in v["reports"]})
                variants.append({"id": _vid(ref, "agg", a), "kpi": ref, "aggregation": a, "filter": "",
                                 "formula": f"{a}({k['name']})" if a != "RATIO" else k["formula"],
                                 "reports": names, "live_reports": _live(k["reports"], names),
                                 "recommended": a == default,
                                 "note": ("FM / semantic-layer default" if a == default else "as authored in reports")})
            groups.append({
                "id": _vid("aggregation", ref), "kind": "aggregation", "title": f"{k['label']} — aggregation rule",
                "kpis": [ref], "domain": k["domain"], "variants": variants,
                "reason": (f"{k['label']} is {k['additivity']}-additive; FM/semantic default is {default} but reports use "
                           + ", ".join(a for a in aggs if a != default)),
            })
        filters = sorted({v["filter"] for v in vs})
        used_filters = [f for f in filters if any(v["filter"] == f and v["reports"] for v in vs)]
        if len(used_filters) > 1:
            variants = []
            for f in filters:
                names = sorted({n for v in vs if v["filter"] == f for n in v["reports"]})
                if not names and f:
                    continue
                variants.append({"id": _vid(ref, "filter", f), "kpi": ref, "aggregation": default,
                                 "filter": f or "(no filter - all rows)",
                                 "formula": f"{default}({k['name']})" + (f" WHERE {f}" if f else ""),
                                 "reports": names, "live_reports": _live(k["reports"], names),
                                 "recommended": not f,
                                 "note": "base definition; filtered variants become slices" if not f else "filtered variant"})
            groups.append({
                "id": _vid("filter", ref), "kind": "filter", "title": f"{k['label']} — filter rule",
                "kpis": [ref], "domain": k["domain"], "variants": variants,
                "reason": f"{k['label']} is reported under {len(variants)} different filter rules",
            })
    # concept groups: configured + same normalized name across entities
    concepts: dict[str, list[str]] = {name: [r for r in refs if r in kpis] for name, refs in cfg.get("kpi_concepts", {}).items()}
    stop = {snake_upper(s) for s in cfg.get("kpi_stopwords", [])}
    by_norm: dict[str, list[str]] = defaultdict(list)
    for ref, k in kpis.items():
        toks = [t for t in snake_upper(k["name"]).split("_") if t not in stop]
        by_norm["_".join(toks)].append(ref)
    covered = {r for refs in concepts.values() for r in refs}
    for norm, refs in sorted(by_norm.items()):
        if len({kpis[r]["entity"] for r in refs}) > 1 and not set(refs) <= covered:
            concepts[title_words(norm).title()] = sorted(refs)
    for name, refs in sorted(concepts.items()):
        if len(refs) < 2:
            continue
        variants = []
        best = max(refs, key=lambda r: (kpis[r]["origin"] == "FM", sum(1 for x in kpis[r]["reports"] if x["disposition"] != "Retire"), r))
        for r in refs:
            k = kpis[r]
            names = sorted({x["report"] for x in k["reports"]})
            variants.append({"id": _vid("concept", name, r), "kpi": r, "aggregation": k["default_aggregation"],
                             "filter": "", "formula": f"{k['default_aggregation']}({r})" + (f"  [{k['unit']}]" if k["unit"] else ""),
                             "reports": names, "live_reports": _live(k["reports"], names), "recommended": r == best,
                             "note": f"{k['origin']} · {', '.join(p.replace('Energy_', '').replace('_Package', '') for p in k['packages'])}"})
        units = sorted({kpis[r]["unit"] or "-" for r in refs})
        groups.append({
            "id": _vid("concept", name), "kind": "concept", "title": name, "kpis": refs,
            "domain": "multiple" if len({kpis[r]["domain"] for r in refs}) > 1 else kpis[refs[0]]["domain"],
            "variants": variants,
            "reason": f"{len(refs)} different items implement '{name}' across "
                      f"{len({p for r in refs for p in kpis[r]['packages']})} packages (units: {', '.join(units)})",
        })
    return groups


def report_kpi_conflicts(catalog: dict) -> dict[str, list[str]]:
    """report -> reasons it uses a KPI definition other than the approved one."""
    out: dict[str, list[str]] = defaultdict(list)
    kpis = {k["id"]: k for k in catalog["kpis"]}
    for grp in catalog["groups"]:
        chosen = grp.get("approved_variant")
        if not chosen:
            continue
        ch = next((v for v in grp["variants"] if v["id"] == chosen), None)
        if ch is None:
            continue
        for v in grp["variants"]:
            if v["id"] == chosen:
                continue
            for rep in v["reports"]:
                if grp["kind"] == "concept":
                    out[rep].append(f"uses {v['kpi']} for '{grp['title']}'; approved definition is {ch['kpi']}")
                elif grp["kind"] == "aggregation":
                    out[rep].append(f"{kpis[v['kpi']]['label']}: report uses {v['aggregation']}; approved rule is {ch['aggregation']}")
                else:
                    out[rep].append(f"{kpis[v['kpi']]['label']}: filter '{v['filter']}' differs from approved '{ch['filter']}'")
    return out
