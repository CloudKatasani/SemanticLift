"""Metadata repository: the canonical graph persisted as relational tables (spec 5).

SQLite is the zero-config default; set SEMLIFT_DB_URL=postgresql://... to use Postgres (requires psycopg).
A Snowflake SEMLIFT_META mirror script is written into every output package.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from ..model import MetaGraph

COLLECTIONS = {
    "source_system": "source_systems", "source_object": "source_objects", "package": "packages",
    "logical_entity": "entities", "logical_attribute": "attributes", "measure": "measures",
    "relationship": "relationships", "hierarchy": "hierarchies", "parameter": "parameters",
    "security_rule": "security_rules", "report": "reports", "intent_cluster": "clusters", "target_object": "targets",
}
LISTS = {"report_item": "report_items", "report_filter": "report_filters", "finding": "findings"}


def _connect(path: Path):
    url = os.environ.get("SEMLIFT_DB_URL", "")
    if url.startswith("postgresql://"):
        import psycopg  # type: ignore
        return psycopg.connect(url), "%s"
    return sqlite3.connect(path), "?"


def save_graph(g: MetaGraph, path: Path, run_id: str) -> None:
    data = g.to_dict()
    conn, ph = _connect(path)
    cur = conn.cursor()
    for table in list(COLLECTIONS) + list(LISTS):
        cur.execute(f"CREATE TABLE IF NOT EXISTS {table} (run_id TEXT, obj_key TEXT, payload TEXT, PRIMARY KEY (run_id, obj_key))")
        cur.execute(f"DELETE FROM {table} WHERE run_id = {ph}", (run_id,))
    for table, attr in COLLECTIONS.items():
        rows = [(run_id, k, json.dumps(v, default=str, sort_keys=True)) for k, v in sorted(data[attr].items())]
        cur.executemany(f"INSERT INTO {table} VALUES ({ph}, {ph}, {ph})", rows)
    for table, attr in LISTS.items():
        rows = [(run_id, f"{i:06d}", json.dumps(v, default=str, sort_keys=True)) for i, v in enumerate(data[attr])]
        cur.executemany(f"INSERT INTO {table} VALUES ({ph}, {ph}, {ph})", rows)
    conn.commit()
    conn.close()


def meta_mirror(g: MetaGraph) -> dict[str, str]:
    """Files for the Snowflake SEMLIFT_META mirror: one JSON-lines file per table + a load script."""
    data = g.to_dict()
    files = {}
    stmts = ["CREATE SCHEMA IF NOT EXISTS SEMLIFT_META;",
             "CREATE STAGE IF NOT EXISTS SEMLIFT_META.LOAD_STAGE FILE_FORMAT = (TYPE = JSON);"]
    for table, attr in list(COLLECTIONS.items()) + list(LISTS.items()):
        coll = data[attr]
        items = list(coll.values()) if isinstance(coll, dict) else coll
        files[f"meta/{table}.jsonl"] = "\n".join(json.dumps(x, default=str, sort_keys=True) for x in items) + "\n"
        stmts += [f"CREATE OR REPLACE TABLE SEMLIFT_META.{table.upper()} (PAYLOAD VARIANT);",
                  f"-- PUT file://meta/{table}.jsonl @SEMLIFT_META.LOAD_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE;",
                  f"COPY INTO SEMLIFT_META.{table.upper()} FROM @SEMLIFT_META.LOAD_STAGE/{table}.jsonl.gz "
                  f"FILE_FORMAT = (TYPE = JSON) MATCH_BY_COLUMN_NAME = NONE;"]
    files["meta/load_semlift_meta.sql"] = "-- Mirror of the SemanticLift canonical model for analysis in Snowflake\n" + "\n".join(stmts) + "\n"
    return files
