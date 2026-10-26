"""RPT adapter: Cognos content export / report specifications (v14-16)."""
from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from .. import expr as cx
from ..model import MetaGraph, Provenance, Report, ReportFilter, ReportItem
from .fm import PARSER, kid, kids, local, text

TYPE_MAP = {"list": "L", "crosstab": "C", "chart": "X", "l": "L", "c": "C", "x": "X"}


def parse_reports(path: Path, rel: str, g: MetaGraph) -> int:
    tree = etree.parse(str(path), PARSER)
    root = tree.getroot()
    if local(root) == "contentExport":
        stated = root.get("totalReports")
        if stated:
            g.stated_counts["rpt_total_reports"] = int(stated)
        g.export_date = (root.get("exportDate") or "")[:10] or g.export_date
        meta = kid(root, "metadata")
        if meta is not None:
            for k in ("totalReports", "activeReports", "archiveDuplicates", "communityDuplicates"):
                v = text(meta, k)
                if v.isdigit():
                    g.stated_counts[f"rpt_{k}"] = int(v)
            pk = kid(meta, "packages")
            for p in (kids(pk, "package") if pk is not None else []):
                g.stated_counts.setdefault("rpt_package_reports", {})[p.get("name")] = int(p.get("reports") or 0)
        reports = kids(root, "report")
    else:
        reports = [root]
    n = 0
    for rep in reports:
        _parse_report(rep, rel, g)
        n += 1
    return n


def _parse_report(rep, rel: str, g: MetaGraph) -> None:
    name = rep.get("name") or text(kid(rep, "reportProperties"), "reportName")
    loc = f"/contentExport/report[@name='{name}']"
    rtype = TYPE_MAP.get((rep.get("type") or "L").lower(), rep.get("type") or "L")
    sim = rep.get("similarityScore")
    props = kid(rep, "reportProperties")
    r = Report(name=name, type=rtype, package=rep.get("package") or "", folder=rep.get("folder") or "",
               path=rep.get("reportPath") or "", dup_group=rep.get("duplicateGroupID") or "",
               similarity=float(sim) if sim else None,
               description=text(props, "description") if props is not None else "",
               prov=Provenance(rel, loc))
    if name in g.reports:
        g.add_finding("F15", "Duplicate report name in export", severity="low", obj=name,
                      evidence=f"{rel}:{loc}")
    g.reports[name] = r
    qs = kid(rep, "queries")
    for q in (kids(qs, "query") if qs is not None else []):
        qname = q.get("name")
        r.query_names.append(qname)
        sel = kid(q, "selection")
        seen: dict[str, int] = {}
        for di in (kids(sel, "dataItem") if sel is not None else []):
            e = cx.normalize(text(di, "expression"))
            item = ReportItem(report=name, query=qname, name=di.get("name"), expression=e,
                              usage=text(di, "usage"), aggregate=di.get("aggregate") or "",
                              rollup_aggregate=di.get("rollupAggregate") or "",
                              prov=Provenance(rel, f"{loc}/queries/query[@name='{qname}']/selection/dataItem[@name='{di.get('name')}']"))
            node, err = cx.try_parse(e)
            if node is not None and isinstance(node, cx.Ref) and len(node.parts) == 3:
                item.ref_package, item.ref_subject, item.ref_item = node.parts
            elif node is not None:
                rs = cx.refs(node)
                if rs and len(rs[0].parts) == 3:
                    item.ref_package, item.ref_subject, item.ref_item = rs[0].parts
            else:
                item.prov.parser_confidence = 0.3
            seen[item.name] = seen.get(item.name, 0) + 1
            if seen[item.name] > 1:
                item.duplicate_name = True
            g.report_items.append(item)
        for kind, container in (("detail", "detailFilters"), ("summary", "summaryFilters")):
            fc = kid(q, container)
            for f in (list(fc) if fc is not None else []):
                if not isinstance(f.tag, str):
                    continue
                ftxt = cx.normalize(text(f, "filterExpression"))
                if not ftxt:
                    continue
                g.report_filters.append(parse_filter(name, qname, ftxt, kind,
                                                     Provenance(rel, f"{loc}/queries/query[@name='{qname}']/{container}")))


def parse_filter(report: str, query: str, ftxt: str, kind: str, prov: Provenance) -> ReportFilter:
    flt = ReportFilter(report=report, query=query, expression=ftxt, kind=kind, prov=prov)
    node, err = cx.try_parse(ftxt)
    if node is None:
        flt.defect = "malformed"
        flt.defect_reason = err or "unparseable"
        m = re.search(r"\[([^\]]+)\]\.\[([^\]]+)\]\.\[([^\]]+)\]", ftxt)
        if m:
            flt.ref_subject, flt.ref_item = m.group(2), m.group(3)
        prov.parser_confidence = 0.3
        return flt
    comps = [n for n in node.walk() if isinstance(n, (cx.BinOp, cx.InList, cx.Between))
             and (not isinstance(n, cx.BinOp) or n.op in ("=", "<>", "<", ">", "<=", ">=", "like"))]
    if comps:
        c = comps[0]
        left = c.left if isinstance(c, cx.BinOp) else c.expr
        right = c.right if isinstance(c, cx.BinOp) else None
        if isinstance(left, cx.Ref) and len(left.parts) == 3:
            flt.ref_subject, flt.ref_item = left.parts[1], left.parts[2]
        flt.operator = c.op if isinstance(c, cx.BinOp) else ("in" if isinstance(c, cx.InList) else "between")
        if isinstance(right, cx.Prompt):
            flt.parameter = right.name
        elif isinstance(right, cx.Literal):
            flt.literal = right.value
        elif isinstance(c, cx.InList):
            ps = [i for i in c.items if isinstance(i, cx.Prompt)]
            if ps:
                flt.parameter = ps[0].name
    return flt
