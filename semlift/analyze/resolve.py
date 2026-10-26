"""Stage 2a - resolve every report data item and filter to an FM object or an inferred entity (FR-03),
and match inferred objects to landed source catalogs (FR-05)."""
from __future__ import annotations

import difflib
import re

from ..model import LogicalAttribute, LogicalEntity, Measure, MetaGraph, Provenance
from ..util import snake_upper

ID_RE = re.compile(r"(ID|Id|Key|Code|Ref)$")


def guess_type(name: str, usage: str) -> str:
    n = name
    if re.search(r"(Date|Due|Start|End)$", n) or n.endswith("Date"):
        return "date"
    if n.startswith(("Is", "Has")) or n.endswith("Flag"):
        return "boolean" if not n.endswith("Flag") else "string"
    if re.search(r"(ID|Key)$", n):
        return "string"
    if usage == "fact":
        if re.search(r"(Count|Affected|Cycles|Days)$", n):
            return "integer"
        return "decimal"
    if re.search(r"(Year|Number|Week)$", n):
        return "integer"
    return "string"


def own_key_of(entity: str, attr_names: list[str]) -> str | None:
    """Identifier whose stem is a prefix of the entity name (OutageID->OutageEvent, RECID->RECCertificate)."""
    for a in attr_names:
        if a.endswith("ID") and len(a) > 2:
            stem = a[:-2]
            if entity.lower().startswith(stem.lower()):
                return a
    return None


def _fm_column_match(g: MetaGraph, entity: LogicalEntity, item: str) -> tuple[str, str] | None:
    """Match an item missing from the FM business layer to a physical column of the entity's source."""
    want = snake_upper(item)
    for so_key in entity.source_objects:
        so = g.source_objects.get(so_key)
        if so and so.column(want):
            return so_key, so.column(want).name
    return None


def resolve(g: MetaGraph, cfg: dict) -> None:
    conf = cfg["confidence"]
    fm_entities = {n for n, e in g.entities.items() if e.origin == "FM"}
    pkg_subjects: dict[str, set[str]] = {}

    for ri in g.report_items:
        if not ri.ref_subject:
            ri.resolution = "unresolved"
            continue
        pkg_subjects.setdefault(ri.ref_package, set()).add(ri.ref_subject)
        ent = g.entities.get(ri.ref_subject)
        if ent is None:
            ent = LogicalEntity(name=ri.ref_subject, origin="inferred", confidence=conf["inferred_only"],
                                description=f"Inferred from report usage in {ri.ref_package}",
                                prov=Provenance(ri.prov.source_file, ri.prov.locator, 0.6))
            g.entities[ri.ref_subject] = ent
        if ri.ref_package not in ent.packages:
            ent.packages.append(ri.ref_package)
        obj = g.item(ent.name, ri.ref_item)
        if obj is None:
            usage = ri.usage
            ident = ri.ref_item.endswith("ID") and usage != "fact"
            prov = Provenance(ri.prov.source_file, ri.prov.locator, 0.6)
            matched = _fm_column_match(g, ent, ri.ref_item) if ent.name in fm_entities else None
            c = conf["inferred_matched"] if matched else conf["inferred_only"]
            so_key, pcol = matched if matched else ("", "")
            dtype = guess_type(ri.ref_item, usage)
            if matched:
                col = g.source_objects[so_key].column(pcol)
                dtype = col.data_type or dtype
            if usage == "fact":
                obj = Measure(entity=ent.name, name=ri.ref_item, physical_column=pcol, source_object=so_key,
                              data_type=dtype, origin="inferred", confidence=c, prov=prov,
                              expression=ri.expression)
                g.measures[f"{ent.name}.{ri.ref_item}"] = obj
            else:
                obj = LogicalAttribute(entity=ent.name, name=ri.ref_item, physical_column=pcol, source_object=so_key,
                                       data_type=dtype, usage="identifier" if ident else "attribute",
                                       origin="inferred", confidence=c, prov=prov, expression=ri.expression)
                g.attributes[f"{ent.name}.{ri.ref_item}"] = obj
        if ri.ref_package not in obj.packages:
            obj.packages.append(ri.ref_package)
        if ri.name != ri.ref_item and ri.name not in obj.labels:
            obj.labels.append(ri.name)
        ri.resolved_entity = ent.name
        ri.resolved_kind = "measure" if isinstance(obj, Measure) else "attribute"
        ri.resolution = "fm" if obj.origin == "FM" else "inferred"

    for f in g.report_filters:
        if f.ref_subject and g.item(f.ref_subject, f.ref_item) is None and f.ref_subject in g.entities:
            ent = g.entities[f.ref_subject]
            g.attributes[f"{ent.name}.{f.ref_item}"] = LogicalAttribute(
                entity=ent.name, name=f.ref_item, data_type=guess_type(f.ref_item, "attr"), origin="inferred",
                confidence=conf["inferred_only"], prov=f.prov)

    g.analysis["package_subjects"] = {k: sorted(v) for k, v in sorted(pkg_subjects.items())}
    _match_catalog(g, cfg)


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _match_catalog(g: MetaGraph, cfg: dict) -> None:
    """FR-05: name, fuzzy and column-overlap matching of entities to landed tables."""
    conf = cfg["confidence"]
    catalog = [so for so in g.source_objects.values() if so.origin == "CATALOG"]
    matches = []
    if not catalog:
        g.analysis["catalog_matches"] = matches
        return
    for ent in sorted(g.entities.values(), key=lambda e: e.name):
        items = g.entity_items(ent.name)
        want_cols = {snake_upper(i.physical_column or i.name) for i in items}
        candidates = []
        if ent.origin == "FM":
            tables = {g.source_objects[k].table for k in ent.source_objects if k in g.source_objects}
        else:
            tables = {snake_upper(ent.name)}
        for so in catalog:
            name_score = 1.0 if so.table in tables else max(
                difflib.SequenceMatcher(None, _norm(so.table), _norm(t)).ratio() for t in tables)
            cols = {c.name for c in so.columns}
            overlap = len(want_cols & cols) / len(want_cols) if want_cols else 0
            score = max(name_score if name_score >= 0.85 else 0, overlap if overlap >= 0.6 else 0)
            method = "name" if name_score == 1.0 else ("fuzzy" if name_score >= 0.85 else "column-overlap")
            if score:
                candidates.append((score, overlap, so.key, method))
        if not candidates:
            continue
        candidates.sort(key=lambda x: (-x[0], -x[1], x[2]))
        score, overlap, key, method = candidates[0]
        so = g.source_objects[key]
        matches.append({"entity": ent.name, "table": f"{so.schema}.{so.table}", "method": method,
                        "score": round(score, 3), "column_overlap": round(overlap, 3)})
        if ent.origin == "FM":
            ent.confidence = conf["fm_catalog_matched"]
        else:
            ent.confidence = max(ent.confidence, conf["inferred_matched"])
            ent.source_objects = [key]
        for it in items:
            col = so.column(snake_upper(it.physical_column or it.name))
            if col is None:
                continue
            if it.origin == "FM":
                it.confidence = conf["fm_catalog_matched"]
            else:
                it.confidence = max(it.confidence, conf["inferred_matched"])
                it.physical_column = col.name
                it.source_object = key
                it.data_type = col.data_type.lower() if col.data_type else it.data_type
    g.analysis["catalog_matches"] = matches
