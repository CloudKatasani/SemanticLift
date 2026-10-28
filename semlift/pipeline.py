"""The seven-stage SemLift pipeline (spec 3): ingest -> rationalize -> design -> review -> generate -> deploy -> validate.

Stages 1-4 run here; review (5) is the human checkpoint in the workspace; deploy (6) and parity
validation (7) run from CI using the generated package.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analyze.aggregates import plan_aggregates
from .analyze.classify import classify
from .analyze.findings import build_findings, check_filter_types
from .analyze.joins import diagnose, infer_relationships
from .analyze.kpis import apply_kpi_decisions, build_kpi_catalog, kpi_override_findings
from .analyze.portfolio import rationalize_reports, source_inventory
from .analyze.rationalize import rationalize
from .analyze.resolve import resolve
from .config import load_config
from .design.engine import build_design
from .design.model import Design
from .generate.snowflake import SnowflakeGenerator
from .ingest import ingest_bundle
from .model import MetaGraph, TargetObject


@dataclass
class RunResult:
    graph: MetaGraph
    design: Design
    objects: list[TargetObject]
    config: dict
    timings: dict[str, float] = field(default_factory=dict)
    compile_results: dict[str, Any] = field(default_factory=dict)


def analyze(g: MetaGraph, cfg: dict, timings: dict) -> None:
    t = time.perf_counter()
    resolve(g, cfg)
    check_filter_types(g)
    classify(g, cfg)
    apply_kpi_decisions(g, cfg)
    infer_relationships(g, cfg)
    timings["model"] = time.perf_counter() - t
    t = time.perf_counter()
    rationalize(g, cfg)
    diagnose(g, cfg)
    timings["rationalize"] = time.perf_counter() - t
    t = time.perf_counter()
    plan_aggregates(g, cfg)
    build_findings(g, cfg)
    kpi_override_findings(g)
    g.analysis["portfolio"] = rationalize_reports(g, cfg, build_kpi_catalog(g, cfg))
    timings["plan"] = time.perf_counter() - t


def run(source: str | Path, work_dir: str | Path, config: str | Path | dict | None = None,
        overrides: dict | None = None, extra_sources: list | None = None,
        suggestions: dict | None = None, decisions: dict | None = None) -> RunResult:
    cfg = dict(config) if isinstance(config, dict) else load_config(config, overrides)
    cfg["_decisions"] = decisions or {}
    timings: dict[str, float] = {}
    t = time.perf_counter()
    g = ingest_bundle(source, work_dir, cfg, extra_sources=extra_sources)
    timings["ingest"] = time.perf_counter() - t
    analyze(g, cfg, timings)
    t = time.perf_counter()
    d = build_design(g, cfg)
    if suggestions:
        from .service.llm import apply_accepted
        apply_accepted(d, suggestions)
    g.analysis["kpi_catalog"] = build_kpi_catalog(g, cfg, d)
    g.analysis["source_inventory"] = source_inventory(g, cfg, d)
    timings["design"] = time.perf_counter() - t
    t = time.perf_counter()
    objects = SnowflakeGenerator(g, d, cfg).generate()
    for o in objects:
        g.targets[o.id] = o
    timings["generate"] = time.perf_counter() - t
    return RunResult(graph=g, design=d, objects=objects, config=cfg, timings=timings)
