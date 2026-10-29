"""Configuration: every design rule threshold and naming override lives here.

Defaults are generic; an estate-specific YAML (see ``config/energy_estate.yaml``)
is deep-merged on top. Same inputs + same configuration => byte-identical outputs.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "as_of_date": None,               # reference date for look-back windows; default = export date
    "rationalization": {
        "lookback_days": 180,
        "min_runs_per_day": 0,         # runs/day <= this counts as "no demand"
        "similarity_threshold": 0.85,  # Jaccard threshold when duplicateGroupID is absent
        "dormant_before": None,        # optional absolute date used for estate stats
        "review_min_runs_per_day": 1,  # live canonical reports below this are flagged Review (low usage)
        "review_stale_days": 90,       # ... or when their last run is older than this
        "consolidate_dim_jaccard": 0.6,  # KPI-subset reports consolidate when dimension overlap >= this
    },
    "confidence": {
        "fm_catalog_matched": 1.0,
        "fm_only": 0.8,
        "inferred_matched": 0.6,
        "inferred_only": 0.3,
        "auto_approve_min": 0.6,
    },
    "aggregates": {
        "coverage_target": 0.80,
        "max_per_fact": 3,
        "min_aggregate_coverage": 0.05,  # each aggregate must serve >= 5% of the fact's weighted demand
        "default_fact_rows": 10_000_000,
        "plain_view_below_rows": 10_000_000,
        "min_reduction_ratio": 10,      # aggregate must be >= 10x smaller than the fact
        "warehouse": "WH_SEMANTIC_REFRESH",
        "warehouse_credits_per_hour": 1.0,   # X-Small
        "scan_rows_per_second": 2_000_000,
        "low_volume_domains": [],       # domains that get plain views only
    },
    "target": {
        "platform": "snowflake",
        "database": "SEMLIFT_DB",
        "tag_schema": "GOV",
        "raw_schema_prefix": "RAW_",
        "raw_schema_overrides": {},     # source database -> RAW schema name
        "refresh_cadence_lag": {"daily": "24 hours", "hourly": "1 hour", "realtime": "5 minutes"},
        "default_refresh_cadence": "daily",
    },
    "security": {
        "precedence": "security_files",  # security_files | model  (which wins on drift)
        "rls_default_deny": True,        # roles neither exempt nor listed are filtered too
        "role_case": "upper",
    },
    "naming": {
        "product_names": {},             # package -> data product display name
        "domain_codes": {},              # package -> short domain code for SV_/DP_ names
        "fact_names": {},                # entity -> fact process name (FCT_<name>)
        "dimension_names": {},           # entity -> dimension name (DIM_<name>)
        "reference_attributes": {},      # attribute -> outrigger dimension name
        "attribute_groups": {},          # outrigger dim -> extra attributes moved with the key
        "policy_names": {},              # Cognos security rule -> platform policy name
        "mapping_table_names": {},       # Cognos security rule -> SEC.MAP_USER_<x>
        "subject_areas": {},             # semantic view name -> {domain, facts:[...], description}
        "aggregate_names": {},
        "package_affixes": [r"_Package$", r"^Package_"],
        "constants_table": "REF_CONSTANT_FACTOR",   # REF table for constants externalized from FM calculations   # regexes stripped from package names for display / codes
    },
    "governance": {
        "four_eyes": False,              # an approver may not approve DDL they edited themselves
    },
    "glossary": {},                      # abbreviation -> expansion used for descriptions and synonyms
    "classification": {
        "static_measure_patterns": ["Capacity", "Installed", "Limit", "Rating", "Approved"],
        "master_entity_patterns": ["Substation", "Plant", "Asset", "Line", "Project", "Charger"],
        "event_entity_patterns": ["Event", "Record", "Submission", "Request", "Complaint", "Violation",
                                  "Service", "Charging", "Settlement", "Cost", "Requirement", "Certificate",
                                  "Forecast", "Actual", "Reading", "Billing", "Generation"],
        "non_additive_patterns": ["Pct", "Percent", "Rate", "Ratio", "Factor", "Score", "Per", "Price",
                                  "Avg", "Average", "Accuracy", "Interval", "Days", "Cycles", "Intensity"],
        "semi_additive_patterns": ["Peak", "Capacity", "Limit", "Max", "Installed", "Balance",
                                   "StateOf", "Level"],
        "power_unit_suffixes": ["MW", "KW", "MVA", "KV"],
        "additive_patterns": ["Amount", "Count", "Cost", "KWh", "MWh", "Minutes", "Penalty", "Charge",
                              "Revenue", "Budget", "Spent", "Value", "Quantity", "Energy", "Emissions",
                              "Affected", "Duration", "MMBTU"],
    },
    "kpi_concepts": {},                # business concept -> [Entity.Measure, ...] defined differently across packages
    "kpi_stopwords": ["Total", "Actual", "Sum"],
    "hierarchies": {
        "Date": ["FiscalYear", "Quarter", "MonthName", "FullDate"],
        "Location": ["Region", "StateProvince", "City", "PostalCode"],
    },
    "cardinality_estimates": {
        "FiscalYear": 6, "Quarter": 4, "MonthName": 12, "MonthNumber": 12, "FullDate": 2200, "ISOWeek": 53,
        "IsWeekend": 2, "IsHoliday": 2, "Region": 5, "StateProvince": 20, "City": 400, "PostalCode": 5000,
        "ClimateZone": 8, "_flag": 2, "_date": 2200, "_status": 6, "_type": 10, "_category": 10, "_segment": 4,
        "_name": 500, "_id": 1_000_000, "_default": 50,
    },
    "llm": {
        "provider": "template",          # template | cortex | anthropic
        "model": None,
        "endpoint": None,
        "domain": "enterprise",          # industry wording used in LLM prompts, e.g. "energy utility"
    },
    "owners": {
        "default_owner": None,           # falls back to FM governance dataOwner
        "default_steward": None,
        "report_owner": "Report owners (per package)",
    },
    "parity": {"tolerance_pct": 0.5, "sample_reports": 20},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = deep_merge(cfg, yaml.safe_load(fh) or {})
    if overrides:
        cfg = deep_merge(cfg, overrides)
    return cfg


# sections whose keys are fixed (anything else is a typo); free-form maps are not checked
_STRICT = ("rationalization", "confidence", "aggregates", "target", "security", "governance", "llm", "owners", "parity")


def validate_config(cfg: dict) -> list[str]:
    """Warnings for unknown keys and wrong value types, so a client config typo never silently does nothing."""
    out = []
    for k in cfg:
        if k not in DEFAULTS and not k.startswith("_"):
            out.append(f"unknown setting '{k}' (ignored)")
    for sec in _STRICT:
        for k, v in (cfg.get(sec) or {}).items():
            if k not in DEFAULTS[sec]:
                out.append(f"unknown setting '{sec}.{k}' (ignored)")
                continue
            d = DEFAULTS[sec][k]
            if isinstance(d, bool) and not isinstance(v, bool):
                out.append(f"'{sec}.{k}' should be true or false")
            elif isinstance(d, (int, float)) and not isinstance(d, bool) and not isinstance(v, (int, float)):
                out.append(f"'{sec}.{k}' should be a number")
    for k in (cfg.get("naming") or {}):
        if k not in DEFAULTS["naming"]:
            out.append(f"unknown setting 'naming.{k}' (ignored)")
    return out
