"""Findings register (spec 2.2 F1-F12 style codes, plus tool-level codes F13+)."""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from .. import expr as cx
from ..model import MetaGraph
from ..design.naming import constants_table
from .rationalize import as_of

CODES = {
    "F1": "Model coverage gap", "F2": "Heavy duplication", "F3": "Duplicates carry the load",
    "F4": "Dormant content", "F5": "No report-level logic", "F6": "Aggregation override is wrong",
    "F7": "Filter type/semantic defect", "F8": "Unused FM logic", "F9": "Model drift",
    "F10": "Conformed dimension", "F11": "Inconsistent counts", "F12": "Hard-coded factor",
    "F13": "Malformed filter expression", "F14": "Join-path issue", "F15": "Duplicate data item name",
    "F16": "Security rule mapping", "F17": "Usage/report orphans", "F18": "Low-confidence inferred object",
    "F19": "Credential exposure masked", "F20": "Security semantics difference",
    "F21": "Steward KPI decision",
}

PARAM_SEMANTICS = {"p_Region": ("Region",), "p_FiscalYear": ("FiscalYear",), "p_Month": ("MonthName", "Month"),
                   "p_Quarter": ("Quarter",), "p_PayStatus": ("PaymentStatus",),
                   "p_CustomerSegment": ("CustomerSegment", "Segment"), "p_SourceCategory": ("SourceCategory",),
                   "p_Standard": ("StandardRef", "StandardID", "Standard"), "p_DateFrom": ("Date",),
                   "p_DateTo": ("Date",)}
TYPE_FAMILY = {"integer": "num", "decimal": "num", "number": "num", "float": "num", "string": "str",
               "date": "date", "datetime": "date", "boolean": "bool"}


def _owner(g: MetaGraph, cfg: dict, kind: str) -> str:
    gov = next(iter(g.governance.values()), {}) if g.governance else {}
    if kind == "report":
        return cfg["owners"]["report_owner"]
    if kind == "steward":
        return cfg["owners"]["default_steward"] or gov.get("steward", "")
    return cfg["owners"]["default_owner"] or gov.get("owner", "")


def check_filter_types(g: MetaGraph) -> None:
    for f in g.report_filters:
        if f.defect or not f.parameter or not f.ref_subject:
            continue
        p = g.parameters.get(f.parameter)
        item = g.item(f.ref_subject, f.ref_item)
        it_type = TYPE_FAMILY.get(getattr(item, "data_type", "string"), "str")
        if p is None:
            f.defect, f.defect_reason = "unknown_parameter", f"?{f.parameter}? is not defined in any parameter map"
            continue
        p_type = TYPE_FAMILY.get(p.data_type, "str")
        p.used_by_filters += 1
        if it_type != p_type:
            f.defect = "type_mismatch"
            f.defect_reason = f"{f.ref_subject}.{f.ref_item} ({it_type}) compared to ?{f.parameter}? ({p.data_type})"
            continue
        sem = PARAM_SEMANTICS.get(f.parameter)
        if sem and not any(s.lower() in f.ref_item.lower() for s in sem):
            f.defect = "semantic_mismatch"
            f.defect_reason = f"{f.ref_subject}.{f.ref_item} compared to ?{f.parameter}? (prompt is for {sem[0]})"


def build_findings(g: MetaGraph, cfg: dict) -> None:
    g.findings = [f for f in g.findings if f.code == "F15"]
    steward, owner, rowner = _owner(g, cfg, "steward"), _owner(g, cfg, "owner"), _owner(g, cfg, "report")
    reps = g.reports
    active = [r for r in reps.values() if r.folder == "Active"]

    # F1 coverage gap
    pkg_subj = g.analysis.get("package_subjects", {})
    total_subj = sum(len(v) for v in pkg_subj.values())
    fm_defined = sum(1 for v in pkg_subj.values() for s in v if g.entities.get(s) and g.entities[s].origin == "FM")
    inferred_refs = [ri for ri in g.report_items if ri.resolution == "inferred" and reps[ri.report].folder == "Active"]
    fm_pkgs = sorted((p for p in g.packages.values() if p.fm_project), key=lambda p: p.name)
    g.add_finding("F1", CODES["F1"], severity="high", obj="estate",
                  evidence=(f"Reports reference {total_subj} package-level query subjects across {len(pkg_subj)} packages; "
                            f"{fm_defined} resolve to an FM definition ({', '.join(p.name for p in fm_pkgs) or 'none'}). "
                            f"{len(inferred_refs)} active data-item references have no FM definition."),
                  owner=steward, resolution="Infer entities from report usage + landed schemas; require catalog access",
                  count=len(inferred_refs))
    for e in sorted(g.entities.values(), key=lambda x: x.name):
        if e.origin == "inferred":
            g.add_finding("F18", f"Inferred entity {e.name} (confidence {e.confidence:.1f})",
                          severity="medium" if e.confidence >= 0.6 else "high", obj=e.name,
                          evidence=f"Used by {', '.join(e.packages)}; no FM definition; generated as stub",
                          owner=steward, resolution="Steward review + source mapping before deployment",
                          blocking=e.confidence < cfg["confidence"]["auto_approve_min"])

    # F2 / F3 duplication
    groups = g.clusters
    sizes = Counter(len(c.members) for c in groups.values())
    folders = Counter(r.folder for r in reps.values())
    runs = defaultdict(float)
    for r in reps.values():
        runs[r.folder] += r.runs_per_day or 0
    dup_reports = sum(n for f, n in folders.items() if f != "Active")
    sims = defaultdict(list)
    for r in reps.values():
        if r.similarity is not None:
            sims[r.folder].append(r.similarity)
    sim_txt = "; ".join(f"{k} {min(v):g}-{max(v):g}%" for k, v in sorted(sims.items()) if k != "Active")
    rat = g.analysis.get("rationalization", {})
    g.add_finding("F2", CODES["F2"], severity="high", obj="estate",
                  evidence=(f"{len(groups)} duplicate groups (sizes {dict(sorted(sizes.items()))}); {dup_reports} archive/community "
                            f"copies of {folders.get('Active', 0)} active reports ({sim_txt}); archive column set equals "
                            f"active in {rat.get('archive_matches_active', 0)} groups; "
                            f"{rat.get('distinct_active_signatures', 0)} distinct active column signatures"),
                  owner=rowner, resolution="Migrate one semantic contract per intent cluster", count=dup_reports)
    total_runs = sum(runs.values()) or 1
    dup_share = 100 * (total_runs - runs.get("Active", 0)) / total_runs
    g.add_finding("F3", CODES["F3"], severity="high", obj="estate",
                  evidence=("Runs/day: " + ", ".join(f"{k} {v:,.0f}" for k, v in sorted(runs.items())) +
                            f" ({total_runs:,.0f} total); duplicates draw {dup_share:.0f}% of runs"),
                  owner=rowner, resolution="Publish redirect map from each retired copy to its canonical report and semantic view",
                  count=int(total_runs))

    # F4 dormant
    ref = as_of(g, cfg)
    window_start = ref - dt.timedelta(days=int(cfg["rationalization"]["lookback_days"]))
    zero = [r for r in reps.values() if (r.runs_per_day or 0) <= cfg["rationalization"]["min_runs_per_day"]]
    stale = [r for r in reps.values() if not r.last_run or dt.date.fromisoformat(r.last_run) < window_start]
    db = cfg["rationalization"].get("dormant_before")
    before = [r for r in reps.values() if db and (not r.last_run or r.last_run < str(db))]
    retired = [c for c in groups.values() if c.disposition == "Retire"]
    g.add_finding("F4", CODES["F4"], severity="medium", obj="estate",
                  evidence=(f"{len(zero)} reports with 0 runs/day; {len(stale)} not run since {window_start} "
                            f"({cfg['rationalization']['lookback_days']}-day window)"
                            + (f"; {len(before)} last run before {db}" if db else "")
                            + f"; {len(retired)} clusters marked Retire"),
                  owner=rowner, resolution="Excluded from design scope (configurable threshold)", count=len(zero))

    # F5 report-level logic
    direct = sum(1 for ri in g.report_items if ri.expression and cx.try_parse(ri.expression)[0].__class__ is cx.Ref)
    aggs = Counter(ri.aggregate for ri in g.report_items)
    calc_items = len(g.report_items) - direct
    g.add_finding("F5", CODES["F5"], severity="info", obj="estate",
                  evidence=(f"{direct} of {len(g.report_items)} data items are direct references; {calc_items} report-level "
                            f"calculations; aggregates used: {dict(sorted(aggs.items()))}"),
                  owner=steward, resolution="Business logic lives in FM; report specs supply grain and filter demand only",
                  count=calc_items)

    # F6 aggregation overrides
    f6 = defaultdict(set)
    for ri in g.report_items:
        if ri.resolved_kind != "measure" or reps[ri.report].folder != "Active":
            continue
        m = g.measures.get(f"{ri.resolved_entity}.{ri.ref_item}")
        if m and ri.aggregate in ("total", "sum") and m.additivity != "additive":
            f6[f"{m.entity}.{m.name}"].add(ri.report)
    numbers_change = []
    for key, rs in sorted(f6.items(), key=lambda x: (g.measures[x[0]].origin != "FM", -len(x[1]), x[0])):
        m = g.measures[key]
        g.add_finding("F6", f"{m.entity}.{m.name} summed by reports; correct aggregation is {m.default_aggregation.upper()}",
                      severity="high" if m.origin == "FM" else "medium", obj=f"{m.entity}.{m.name}",
                      evidence=(f"{len(rs)} active reports apply 'total' to a {m.additivity}-additive measure "
                                f"(rule {m.rule}{', FM regularAggregate=' + m.regular_aggregate if m.regular_aggregate else ''}): "
                                + ", ".join(sorted(rs)[:8]) + (" ..." if len(rs) > 8 else "")),
                      owner=rowner, resolution="Semantic metric enforces default aggregation; publish 'numbers that will change'",
                      count=len(rs))
        for r in sorted(rs):
            numbers_change.append({"report": r, "measure": f"{m.entity}.{m.name}", "cognos": "SUM",
                                   "semantic": m.default_aggregation.upper(), "origin": m.origin})
    g.analysis["numbers_that_change"] = numbers_change

    # F7 / F13 filter defects
    by_defect = defaultdict(list)
    for f in g.report_filters:
        if f.defect:
            by_defect[(f.defect, f.ref_subject, f.ref_item, f.parameter or "")].append(f)
    for (kind, subj, item, param), fl in sorted(by_defect.items()):
        code = "F13" if kind == "malformed" else "F7"
        sev = "high" if kind in ("type_mismatch", "malformed", "unknown_parameter") else "medium"
        nrep = len({f.report for f in fl})
        nact = len({f.report for f in fl if reps[f.report].folder == "Active"})
        g.add_finding(code, f"{subj}.{item} " + (f"vs ?{param}?: {kind.replace('_', ' ')}" if param else "malformed filter"),
                      severity=sev, obj=f"{subj}.{item}",
                      evidence=f"{len(fl)} filters in {nrep} reports ({nact} active); e.g. {fl[0].expression!r}; {fl[0].defect_reason}",
                      owner=rowner, resolution="Do not replicate; route to report owners", count=len(fl))

    # F8 unused FM logic
    used = {f"{ri.resolved_entity}.{ri.ref_item}" for ri in g.report_items if reps[ri.report].folder == "Active"}
    used |= {f"{f.ref_subject}.{f.ref_item}" for f in g.report_filters if reps[f.report].folder == "Active"}
    fm_items = [o for o in list(g.attributes.values()) + list(g.measures.values()) if o.origin == "FM"]
    unused = sorted(f"{o.entity}.{o.name}" for o in fm_items if f"{o.entity}.{o.name}" not in used)
    unused_calc = sorted(f"{o.entity}.{o.name}" for o in fm_items if f"{o.entity}.{o.name}" not in used and o.is_calculated)
    g.analysis["unused_fm_items"] = unused
    g.add_finding("F8", CODES["F8"], severity="low", obj="FM Business Layer",
                  evidence=(f"{len(unused)} of {len(fm_items)} Business-layer items unused by active reports; calculated: "
                            + ", ".join(unused_calc)),
                  owner=steward, resolution="Keep calculations as semantic metrics; drop unused raw attributes from presentation contract",
                  count=len(unused))

    # F9 drift
    drift_items = sorted({f"{o.entity}.{o.name}" for o in list(g.attributes.values()) + list(g.measures.values())
                          if o.origin == "inferred" and g.entities.get(o.entity) and g.entities[o.entity].origin == "FM"})
    if drift_items:
        g.add_finding("F9", "Reports use items absent from FM", severity="medium", obj="FM Business Layer",
                      evidence=", ".join(drift_items) + ". Matched to FM physical columns: " + (", ".join(
                          f"{o.entity}.{o.name}->{o.physical_column}" for o in list(g.attributes.values()) + list(g.measures.values())
                          if o.origin == "inferred" and o.physical_column and g.entities[o.entity].origin == "FM") or "none"),
                      owner=steward, resolution="Reconcile against source catalogs; add to model", count=len(drift_items))
    for r in sorted(g.security_rules.values(), key=lambda r: r.name):
        tgt = [r.target_entity] if r.target_entity else [t["entity"] for t in r.targets]
        for t in tgt:
            if r.type == "namespace":
                continue
            e = g.entities.get(t)
            if e is None or e.origin != "FM":
                g.add_finding("F9", f"Security rule {r.name} targets {t}, which is not in the FM model",
                              severity="medium", obj=r.name, evidence=f"{r.prov.source_file}:{r.prov.locator}" if r.prov else "",
                              owner=steward, resolution="Policy generated on inferred object; confirm target")
                break
    sec_secondary = g.analysis.get("security_secondary", [])
    for r in sorted(g.security_rules.values(), key=lambda r: r.name):
        for s in sec_secondary:
            if s.type == r.type and s.target_entity == r.target_entity and s.target_item == r.target_item and s.target_item:
                if sorted(s.roles_in) != sorted(r.roles_in):
                    g.add_finding("F9", f"{r.target_entity}.{r.target_item} grants differ between security sources",
                                  severity="high", obj=f"{r.target_entity}.{r.target_item}",
                                  evidence=(f"{r.prov.source_file if r.prov else r.origin}: {len(r.roles_in)} roles {sorted(r.roles_in)}; "
                                            f"{s.prov.source_file if s.prov else s.origin}: {len(s.roles_in)} roles {sorted(s.roles_in)}. "
                                            f"Using {cfg['security']['precedence']}."),
                                  owner=steward, resolution="Open question: confirm authoritative grant")
    for pkg, diffs in sorted(g.analysis.get("fm_drift", {}).items()):
        g.add_finding("F9", f"model.xml vs package.xml for {pkg}: {len(diffs)} differences",
                      severity="medium" if diffs else "info", obj=pkg,
                      evidence="; ".join(diffs[:10]) if diffs else "Structurally identical (comments only); package.xml used",
                      owner=steward, resolution="package.xml (published) wins")
    for ns in g.analysis.get("ns_summaries", []):
        for q in ns["querySubjects"]:
            stated = int(q.get("itemCount") or 0)
            if ns["type"] == "business":
                actual = len(g.entity_items(q["name"])) - len([o for o in g.entity_items(q["name"]) if o.origin != "FM"])
            else:
                so = g.source_objects.get(q["name"])
                actual = len(so.columns) if so else 0
            if stated and actual and stated != actual:
                g.add_finding("F9", f"{ns['name']}.{q['name']} itemCount {stated} in .ns vs {actual} in model",
                              severity="low", obj=q["name"], evidence=ns["file"], owner=steward,
                              resolution="Regenerate namespace summaries")

    # F10 conformed dimensions
    for ent, info in g.analysis.get("conformed", {}).items():
        ext = {p: v for p, v in info["extensions"].items() if v}
        g.add_finding("F10", f"Conformed dimension {ent} used by {len(info['packages'])} packages",
                      severity="info" if not ext else "medium", obj=ent,
                      evidence=f"core attributes {info['core']}; package extensions {ext}",
                      owner=steward, resolution=f"Build one conformed DIM with mastered keys; extensions become columns")

    # F11 counts
    sc = g.stated_counts
    checks = []
    if "usage_title_reports" in sc:
        checks.append(("usage title reports", sc["usage_title_reports"], len(g.usage_rows)))
    if "usage_title_per_category" in sc:
        checks.append(("usage title per category", sc["usage_title_per_category"], len(active)))
    if "rpt_total_reports" in sc:
        checks.append(("report export totalReports", sc["rpt_total_reports"], len(reps)))
    for pkg, n in sorted(sc.get("rpt_package_reports", {}).items()):
        checks.append((f"{pkg} reports", n, sum(1 for r in reps.values() if r.package == pkg)))
    mism = [c for c in checks if c[1] != c[2]]
    g.analysis["count_reconciliation"] = [{"check": c[0], "stated": c[1], "actual": c[2], "ok": c[1] == c[2]} for c in checks]
    g.add_finding("F11", CODES["F11"], severity="low" if mism else "info", obj="ingest",
                  evidence="; ".join(f"{c[0]}: stated {c[1]}, actual {c[2]}" for c in (mism or checks)),
                  owner=steward, resolution="Validator reconciles stated vs actual counts on ingest", count=len(mism))

    # F12 hard-coded constants
    for m in sorted(list(g.measures.values()) + list(g.attributes.values()), key=lambda o: (o.entity, o.name)):
        if m.origin != "FM" or not m.expression:
            continue
        node, _ = cx.try_parse(m.expression)
        consts = cx.numeric_constants(node) if node is not None else []
        if consts:
            g.add_finding("F12", f"{m.entity}.{m.name} uses literal {', '.join(str(c) for c in consts)}",
                          severity="medium", obj=f"{m.entity}.{m.name}",
                          evidence=f"{m.expression}" + (f" ({m.description})" if getattr(m, "description", "") else ""),
                          owner=steward, resolution=f"Externalize to {constants_table(cfg)} with effective dates")

    # F14 join issues
    for j in g.analysis.get("join_issues", []):
        sev = {"fan_trap": "high", "chasm_trap": "medium", "missing_relationship": "high", "ambiguous": "medium"}[j["kind"]]
        a, b = j["key"]
        g.add_finding("F14", f"{j['kind'].replace('_', ' ')}: {a} / {b}", severity=sev, obj=f"{a}->{b}",
                      evidence=f"{j['count']} report queries; {j['detail']}; e.g. {', '.join(j['reports'][:3])}",
                      owner=steward, resolution={
                          "fan_trap": "Excluded from aggregates; add a fact-level key before joining",
                          "chasm_trap": "Model as separate facts; semantic view metrics aggregate per fact grain",
                          "missing_relationship": "Add relationship / key mapping in CORE",
                          "ambiguous": "Pick a role-playing path; declare it in the semantic view"}[j["kind"]],
                      count=j["count"])

    # F15 duplicate data item names
    dups = defaultdict(set)
    for ri in g.report_items:
        if ri.duplicate_name:
            dups[ri.report].add(ri.name)
    dup_inactive = {r: n for r, n in dups.items() if reps[r].folder != "Active"}
    for rep, names in sorted(dups.items()):
        if rep in dup_inactive:
            continue
        g.add_finding("F15", f"Duplicate data item name in {rep}", severity="medium", obj=rep,
                      evidence=f"{sorted(names)} ({reps[rep].folder})", owner=rowner,
                      resolution="Rename before migration; semantic contract keeps one column")
    if dup_inactive:
        g.add_finding("F15", f"Duplicate data item names in {len(dup_inactive)} archive/community reports",
                      severity="low", obj="duplicates", count=len(dup_inactive),
                      evidence="; ".join(f"{r}: {sorted(n)}" for r, n in sorted(dup_inactive.items())[:12]) + " ...",
                      owner=rowner, resolution="Resolved by rationalization (copies merge into canonical)")

    # F17 orphans
    uj = g.analysis.get("usage_join", {})
    if uj.get("usage_orphans") or uj.get("reports_without_usage"):
        g.add_finding("F17", CODES["F17"], severity="low", obj="usage",
                      evidence=f"usage rows without report: {uj.get('usage_orphans', [])[:10]}; reports without usage: {uj.get('reports_without_usage', [])[:10]}",
                      owner=rowner, resolution="Treated as zero demand")
    else:
        g.add_finding("F17", "Usage joins every report", severity="info", obj="usage",
                      evidence=f"{uj.get('matched', 0)} of {uj.get('usage_rows', 0)} usage rows matched by report_name/report_path",
                      owner=rowner, resolution="None")

    # F19 credentials
    for ss in g.source_systems.values():
        if ss.connection:
            g.add_finding("F19", f"Connection details for {ss.name} masked in outputs", severity="info", obj=ss.name,
                          evidence=f"JDBC URL stored as {ss.connection}", owner=owner, resolution="No credentials exported")
    if cfg["security"]["rls_default_deny"]:
        g.add_finding("F20", "Row filters become deny-by-default", severity="low", obj="SEC",
                      evidence="Cognos applies securityFilter only to 'appliesTo' roles; generated policies filter every role that is not exempt",
                      owner=steward, resolution="Set security.rls_default_deny=false to mirror Cognos exactly")
