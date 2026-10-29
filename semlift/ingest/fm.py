"""FM-PROJ, FM-NS, FM-SEC, FM-PARAM and FM-DS adapters (spec 4.2 'FM model')."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from lxml import etree

from .. import expr as cx
from ..model import (LogicalAttribute, LogicalEntity, MetaGraph, Measure, Parameter, Provenance,
                     Relationship, SecurityRule, SourceColumn, SourceObject, SourceSystem)
from ..util import mask_secret_url

PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True, huge_tree=True)


def local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def kids(el, name: str) -> list:
    return [c for c in el if isinstance(c.tag, str) and local(c) == name]


def kid(el, name: str):
    for c in el:
        if isinstance(c.tag, str) and local(c) == name:
            return c
    return None


def text(el, name: str, default: str = "") -> str:
    c = kid(el, name)
    return (c.text or "").strip() if c is not None and c.text else default


def desc(el, name: str) -> list:
    return [c for c in el.iter() if isinstance(c.tag, str) and local(c) == name]


def xpath_of(el) -> str:
    """Readable, namespace-free XPath (e.g. /project/namespace[2]/querySubject[3])."""
    parts = []
    while el is not None and isinstance(el.tag, str):
        parent = el.getparent()
        name = local(el)
        if parent is not None:
            same = [c for c in parent if isinstance(c.tag, str) and local(c) == name]
            idx = same.index(el) + 1
            label = f"{name}[{idx}]" if len(same) > 1 else name
            if el.get("name"):
                label = f"{name}[@name='{el.get('name')}']"
        else:
            label = name
        parts.append(label)
        el = parent
    return "/" + "/".join(reversed(parts))


def roles(el, container: str) -> list[str]:
    c = kid(el, container) if el is not None else None
    return [r.get("name") for r in kids(c, "role")] if c is not None else []


def _bool(v: Optional[str]) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y")


# --------------------------------------------------------------------------- FM model
def parse_fm_model(path: Path, rel: str) -> dict:
    """Parse model.xml / package.xml into a plain dict (kept for drift diff)."""
    tree = etree.parse(str(path), PARSER)
    root = tree.getroot()
    fm: dict[str, Any] = {
        "file": rel, "schema": etree.QName(root).namespace, "version": root.get("version"),
        "cognos_version": root.get("cognosVersion"), "description": text(root, "description"),
        "governance": {}, "data_sources": [], "namespaces": {}, "relationships": [], "parameter_maps": [],
        "security": {"row": [], "ols": [], "abac": []}, "folders": {}, "package_name": "",
        "data_modules": [],
    }
    gov = kid(root, "governanceMetadata")
    if gov is not None:
        lin = kid(gov, "dataLineage")
        fm["governance"] = {
            "owner": text(gov, "dataOwner"), "steward": text(gov, "dataSteward"),
            "classification": text(gov, "dataClassification"), "retention": text(gov, "retentionPolicy"),
            "tags": [t.text for t in desc(gov, "tag") if t.text],
            "lineage": [dict(s.attrib) for s in kids(lin, "source")] if lin is not None else [],
        }
    for ds in kids(root, "dataSource"):
        conn = kid(ds, "connection")
        fm["data_sources"].append({
            "name": ds.get("name"), "vendor": ds.get("vendor"), "type": ds.get("type"),
            "schema": text(conn, "schema") if conn is not None else "",
            "catalog": text(conn, "catalog") if conn is not None else "",
            "url": mask_secret_url(text(conn, "contentManagerURL")) if conn is not None else "",
        })
    for dm in kids(root, "dataModule"):
        fm["data_modules"].append(dm.get("name"))
    pub = kid(root, "publishSettings")
    if pub is not None:
        fm["package_name"] = text(pub, "packageName")

    def walk_ns(ns_el):
        ns_name = ns_el.get("name")
        qss = {}
        for qs in desc(ns_el, "querySubject"):
            items = []
            for qi in desc(qs, "queryItem"):
                items.append({
                    "name": qi.get("name"), "dataType": qi.get("dataType") or "string",
                    "usage": qi.get("usage") or "attribute",
                    "regularAggregate": qi.get("regularAggregate") or "none",
                    "expression": cx.normalize(text(qi, "expression")),
                    "description": text(qi, "description"),
                    "sensitive": _bool(text(qi, "sensitiveData", "false")),
                    "xpath": xpath_of(qi),
                })
            qss[qs.get("name")] = {
                "name": qs.get("name"), "type": qs.get("type"), "dataSource": qs.get("dataSource"),
                "dbQuery": cx.normalize(text(qs, "dbQuery")), "description": text(qs, "description"),
                "items": items, "xpath": xpath_of(qs),
            }
        folders = {}
        for f in kids(ns_el, "folder"):
            folders[f.get("name")] = [i.get("refObject") for i in kids(f, "item")]
        for pm in kids(ns_el, "parameterMap"):
            fm["parameter_maps"].append({
                "name": pm.get("name"), "xpath": xpath_of(pm),
                "parameters": [dict(p.attrib) for p in kids(pm, "parameter")]})
        types = {q["type"] for q in qss.values()}
        if folders and not qss:
            kind = "presentation"
        elif "dataSourceQuerySubject" in types:
            kind = "physical"
        elif "modelQuerySubject" in types:
            kind = "business"
        else:
            kind = "unknown"
        fm["namespaces"][ns_name] = {"name": ns_name, "type": kind, "querySubjects": qss,
                                     "description": text(ns_el, "description"), "folders": folders}
        if folders:
            fm["folders"].update(folders)
            if not fm["package_name"]:
                fm["package_name"] = ns_name

    if any(qs.get("name") is None and kid(qs, "name") is not None for qs in desc(root, "querySubject")):
        raise ValueError("native Framework Manager model.xml layout (names as child elements) is not supported yet; "
                         "reports are still analysed and their entities inferred - see the Cognos export guide")
    for ns_el in kids(root, "namespace"):
        walk_ns(ns_el)
    rels = kid(root, "relationships")
    for r in (kids(rels, "relationship") if rels is not None else []):
        jf = kid(r, "joinFilter")
        fm["relationships"].append({
            "name": r.get("name"), "left": r.get("left"), "right": r.get("right"),
            "cardinality": r.get("cardinality") or "n:1", "joinType": r.get("joinType") or "inner",
            "expression": cx.normalize(text(jf, "expression")) if jf is not None else "",
            "xpath": xpath_of(r),
        })
    sec = kid(root, "security")
    if sec is not None:
        fm["security"] = parse_security_block(sec, rel, origin="FM-MODEL")
    return fm


# --------------------------------------------------------------------------- security
def _split_ref(ref: str) -> tuple[str, str, str]:
    """'Business Layer.Billing.BillAmount' -> (ns, qs, item)."""
    parts = (ref or "").split(".")
    if len(parts) >= 3:
        return parts[0], parts[1], ".".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return "", ref or "", ""


def parse_security_block(el, rel: str, origin: str) -> dict:
    out = {"row": [], "ols": [], "abac": [], "namespace": []}
    for sf in desc(el, "securityFilter"):
        tqs = sf.get("targetQuerySubject") or ""
        ns = sf.get("targetNamespace") or ""
        if "." in tqs and not ns:
            ns, tqs, _ = _split_ref(tqs + ".x")
        out["row"].append(SecurityRule(
            name=sf.get("name"), type="row", target_entity=tqs,
            predicate=cx.normalize(text(sf, "expression")), roles_in=roles(sf, "appliesTo"),
            roles_exempt=roles(sf, "exemptRoles"), description=cx.normalize(text(sf, "description")),
            enabled=sf.get("enabled", "true") != "false", origin=origin,
            prov=Provenance(rel, xpath_of(sf))))
    for so in desc(el, "securedObject"):
        if so.get("querySubject"):
            qs, item = so.get("querySubject"), so.get("queryItem") or ""
        else:
            _, qs, item = _split_ref(so.get("name"))
        name = so.get("name") if so.get("querySubject") else (item or so.get("name"))
        out["ols"].append(SecurityRule(
            name=name, type="column_grant", target_entity=qs, target_item=item,
            roles_in=roles(so, "allowedRoles"), roles_denied=roles(so, "deniedRoles"), origin=origin,
            prov=Provenance(rel, xpath_of(so))))
        mk = kid(so, "masking")
        if mk is not None:
            mr = kid(mk, "maskingRule")
            out["ols"].append(SecurityRule(
                name=f"{item}_Mask", type="mask", target_entity=qs, target_item=item,
                roles_in=roles(so, "allowedRoles"),
                roles_denied=roles(mr, "applyToRoles") if mr is not None else [],
                masked_value=text(mr, "maskedValue") if mr is not None else "", origin=origin,
                prov=Provenance(rel, xpath_of(mk))))
    for cm in desc(el, "columnMasking"):
        out["ols"].append(SecurityRule(
            name=cm.get("name"), type="mask", target_entity=cm.get("querySubject") or "",
            target_item=cm.get("queryItem") or "", roles_in=roles(cm, "allowedRoles"),
            roles_denied=roles(cm, "maskingRoles"), masked_value=text(cm, "maskedValue"),
            description=cx.normalize(text(cm, "description")), origin=origin,
            prov=Provenance(rel, xpath_of(cm))))
    for pol in desc(el, "policy"):
        targets = []
        tg = kid(pol, "targets")
        for t in (kids(tg, "target") if tg is not None else []):
            if t.get("refObject"):
                _, qs, item = _split_ref(t.get("refObject"))
            else:
                qs, item = t.get("querySubject") or "", t.get("queryItem") or ""
            targets.append({"entity": qs, "item": item})
        out["abac"].append(SecurityRule(
            name=pol.get("name"), type="abac", predicate=cx.normalize(text(pol, "condition")),
            effect=text(pol, "effect"), targets=targets, description=cx.normalize(text(pol, "description")),
            origin=origin, prov=Provenance(rel, xpath_of(pol))))
    nv = kid(el, "namespaceVisibility")
    if nv is not None:
        for ns in kids(nv, "namespace"):
            out["namespace"].append(SecurityRule(
                name=ns.get("name"), type="namespace", target_entity=ns.get("name"),
                roles_in=roles(ns, "allowedRoles"), roles_denied=roles(ns, "deniedRoles"), origin=origin,
                prov=Provenance(rel, xpath_of(ns))))
    return out


def parse_security_file(path: Path, rel: str) -> dict:
    root = etree.parse(str(path), PARSER).getroot()
    return parse_security_block(root, rel, origin="FM-SEC")


# --------------------------------------------------------------------------- params / ds / ns / cpf
def parse_parameter_map(path: Path, rel: str) -> list[Parameter]:
    root = etree.parse(str(path), PARSER).getroot()
    out = []
    for p in kids(root, "parameter"):
        pl = kid(p, "pickList")
        dv = text(p, "defaultValue") or None
        out.append(Parameter(
            name=p.get("name"), data_type=text(p, "dataType", "string"), default=dv,
            pick_list=[{"value": i.get("value"), "label": i.get("label")} for i in kids(pl, "item")] if pl is not None else [],
            required=_bool(text(p, "required", "false")), multi_select=_bool(text(p, "multiSelect", "false")),
            validation=text(p, "validationRule"), prompt_text=text(p, "promptText"),
            origin="FM-PARAM", prov=Provenance(rel, xpath_of(p))))
    return out


def parse_datasource(path: Path, rel: str) -> dict:
    root = etree.parse(str(path), PARSER).getroot()
    jdbc = kid(root, "jdbcConnection")
    tables = kid(root, "tables")
    return {
        "name": root.get("name"), "vendor": text(root, "vendor"), "vendor_version": text(root, "vendorVersion"),
        "url": mask_secret_url(text(jdbc, "url")) if jdbc is not None else "",
        "schema": text(jdbc, "schema") if jdbc is not None else "",
        "catalog": text(jdbc, "catalog") if jdbc is not None else "",
        "tables": [(t.get("schema"), t.get("name")) for t in kids(tables, "table")] if tables is not None else [],
        "file": rel,
    }


def parse_namespace_summary(path: Path, rel: str) -> dict:
    root = etree.parse(str(path), PARSER).getroot()
    qss = kid(root, "querySubjects")
    return {"name": root.get("name"), "type": root.get("type"), "file": rel,
            "querySubjects": [dict(q.attrib) for q in kids(qss, "querySubject")] if qss is not None else []}


def parse_cpf(path: Path, rel: str) -> dict:
    root = etree.parse(str(path), PARSER).getroot()
    nss = kid(root, "namespaces")
    pf = kid(root, "projectFiles")
    return {"name": text(root, "projectName"), "file": rel, "version": root.get("version"),
            "namespaces": [dict(n.attrib) for n in kids(nss, "namespace")] if nss is not None else [],
            "files": [dict(f.attrib) for f in kids(pf, "file")] if pf is not None else []}


# --------------------------------------------------------------------------- diff
def diff_models(a: dict, b: dict) -> list[str]:
    """Structural diff of two parsed FM models (model.xml vs package.xml)."""
    diffs: list[str] = []

    def items(fm):
        out = {}
        for ns in fm["namespaces"].values():
            for qs in ns["querySubjects"].values():
                for it in qs["items"]:
                    out[f"{ns['name']}.{qs['name']}.{it['name']}"] = (
                        it["dataType"], it["usage"], it["regularAggregate"], it["expression"])
        return out

    ia, ib = items(a), items(b)
    for k in sorted(set(ia) | set(ib)):
        if k not in ia:
            diffs.append(f"only in {b['file']}: {k}")
        elif k not in ib:
            diffs.append(f"only in {a['file']}: {k}")
        elif ia[k] != ib[k]:
            diffs.append(f"changed {k}: {ia[k]} -> {ib[k]}")
    ra = {r["name"]: (r["left"], r["right"], r["cardinality"], r["expression"]) for r in a["relationships"]}
    rb = {r["name"]: (r["left"], r["right"], r["cardinality"], r["expression"]) for r in b["relationships"]}
    for k in sorted(set(ra) | set(rb)):
        if ra.get(k) != rb.get(k):
            diffs.append(f"relationship {k} differs")
    return diffs


# --------------------------------------------------------------------------- load into graph
def load_fm_into_graph(g: MetaGraph, fm: dict, cfg: dict) -> None:
    """Physical layer -> source objects; business layer -> FM entities, attributes, measures."""
    pkg = fm["package_name"] or Path(fm["file"]).stem
    rel = fm["file"]
    phys_ns = [ns for ns in fm["namespaces"].values() if ns["type"] == "physical"]
    biz_ns = [ns for ns in fm["namespaces"].values() if ns["type"] == "business"]
    ds_by_name = {d["name"]: d for d in fm["data_sources"]}
    lineage = (fm.get("governance") or {}).get("lineage") or []
    cadence = lineage[0].get("refreshCadence", "daily") if lineage else "daily"

    for d in fm["data_sources"]:
        sysname = d["catalog"] or d["schema"] or d["name"]
        g.source_systems.setdefault(sysname, SourceSystem(
            name=sysname, vendor=d["vendor"] or "", database=sysname, schema=d["schema"],
            refresh_cadence=cadence, connection=d["url"], origin="FM-PROJ", prov=Provenance(rel, "/project/dataSource")))

    phys_cols: dict[str, dict[str, dict]] = {}
    for ns in phys_ns:
        for qs in ns["querySubjects"].values():
            ds = ds_by_name.get(qs["dataSource"], {})
            table = qs["dbQuery"].split()[-1] if qs["dbQuery"] else qs["name"]
            schema, _, tname = table.rpartition(".")
            so = SourceObject(
                key=qs["name"], system=ds.get("catalog") or ds.get("schema") or "", schema=schema or ds.get("schema", ""),
                table=tname, origin="FM", sql=qs["dbQuery"], prov=Provenance(rel, qs["xpath"]),
                columns=[SourceColumn(i["name"], i["dataType"], i["usage"], i["regularAggregate"], i["sensitive"])
                         for i in qs["items"]])
            g.source_objects[qs["name"]] = so
            phys_cols[qs["name"]] = {i["name"]: i for i in qs["items"]}

    conf_fm = cfg["confidence"]["fm_only"]
    for ns in biz_ns:
        for qs in ns["querySubjects"].values():
            ent = LogicalEntity(name=qs["name"], origin="FM", confidence=conf_fm, packages=[pkg],
                                description=qs["description"], prov=Provenance(rel, qs["xpath"]))
            sources: list[str] = []
            for it in qs["items"]:
                node, err = cx.try_parse(it["expression"]) if it["expression"] else (None, "empty")
                rs = cx.refs(node) if node is not None else []
                phys_refs = [r for r in rs if len(r.parts) == 3 and r.parts[1] in phys_cols]
                for r in phys_refs:
                    if r.parts[1] not in sources:
                        sources.append(r.parts[1])
                single = node is not None and cx.is_single_ref(node) and phys_refs
                pcol = phys_refs[0].parts[2] if single else ""
                psrc = phys_refs[0].parts[1] if phys_refs else ""
                calc = not single
                prov = Provenance(rel, it["xpath"], 1.0 if err is None else 0.5)
                if it["usage"] == "fact":
                    m = Measure(entity=qs["name"], name=it["name"], physical_column=pcol, source_object=psrc,
                                data_type=it["dataType"], expression=it["expression"],
                                regular_aggregate=it["regularAggregate"], is_calculated=calc,
                                description=it["description"], origin="FM", confidence=conf_fm,
                                sensitive=it["sensitive"], packages=[pkg], prov=prov)
                    if node is not None:
                        divs = [n for n in node.walk() if isinstance(n, cx.BinOp) and n.op == "/"]
                        if divs and it["regularAggregate"] == "calculated":
                            num = [r.parts[-1] for r in cx.refs(divs[0].left)]
                            den = [r.parts[-1] for r in cx.refs(divs[0].right)]
                            if num and den:
                                m.is_ratio = True
                                m.ratio_parts = [num[0], den[0]]
                    g.measures[f"{qs['name']}.{it['name']}"] = m
                else:
                    g.attributes[f"{qs['name']}.{it['name']}"] = LogicalAttribute(
                        entity=qs["name"], name=it["name"], physical_column=pcol, source_object=psrc,
                        data_type=it["dataType"], usage=it["usage"], sensitive=it["sensitive"],
                        description=it["description"], expression=it["expression"], is_calculated=calc,
                        origin="FM", confidence=conf_fm, packages=[pkg], prov=prov)
            ent.source_objects = sources
            g.entities[qs["name"]] = ent

    # physical relationships -> entity relationships
    phys_to_ent = {}
    for e in g.entities.values():
        if e.origin == "FM" and e.source_objects:
            phys_to_ent.setdefault(e.source_objects[0], e.name)
    for r in fm["relationships"]:
        le, re_ = phys_to_ent.get(r["left"]), phys_to_ent.get(r["right"])
        if not le or not re_:
            continue
        node, _ = cx.try_parse(r["expression"])
        keys = []
        if node is not None:
            for eq in [n for n in node.walk() if isinstance(n, cx.BinOp) and n.op == "="]:
                lr, rr = cx.refs(eq.left), cx.refs(eq.right)
                if lr and rr:
                    a, b = lr[0].parts, rr[0].parts
                    if a[-2] == r["right"]:
                        a, b = b, a
                    keys.append((a[-1], b[-1]))
        g.relationships[r["name"]] = Relationship(
            name=r["name"], from_entity=le, to_entity=re_, cardinality=r["cardinality"], join_type=r["joinType"],
            join_keys=keys, origin="FM", confidence=conf_fm, expression=r["expression"],
            prov=Provenance(rel, r["xpath"]))
    g.fm_models[pkg] = fm
    gov = fm.get("governance") or {}
    if gov:
        g.governance.setdefault(pkg, gov)
