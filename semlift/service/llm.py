"""LLM assist (FR-15): draft descriptions, synonyms and verified-query wording.

Every suggestion is stored with status ``suggested`` and only reaches generated objects after a
steward accepts it. The default ``template`` provider is deterministic and offline; ``cortex``
calls SNOWFLAKE.CORTEX.COMPLETE inside the client tenant; ``anthropic`` calls an approved endpoint.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from ..design.model import Design
from ..model import MetaGraph
from ..util import stable_hash, title_words

ABBREV = {"kwh": "kilowatt hours", "mwh": "megawatt hours", "kw": "kilowatts", "mw": "megawatts", "pct": "percent",
          "co2": "carbon dioxide", "usd": "US dollars", "mmbtu": "million BTU", "nps": "net promoter score",
          "saidi": "system average interruption duration index", "saifi": "system average interruption frequency index",
          "maifi": "momentary average interruption frequency index", "rec": "renewable energy certificate",
          "ev": "electric vehicle", "gl": "general ledger", "kv": "kilovolts", "mva": "megavolt amperes", "fy": "fiscal year"}


def expand(words: str) -> str:
    return " ".join(ABBREV.get(w, w) for w in words.split())


class TemplateProvider:
    name = "template"

    def describe(self, kind: str, name: str, context: str) -> dict:
        words = title_words(name)
        exp = expand(words)
        syn = sorted({exp} - {words}) if exp != words else []
        desc = f"{exp[:1].upper()}{exp[1:]}" + (f" ({context})" if context else "")
        return {"description": desc, "synonyms": syn}


class CortexProvider:  # pragma: no cover - requires a live account
    name = "cortex"

    def __init__(self, model: str | None):
        from .compile import live_connection
        self.conn = live_connection()
        self.model = model or "claude-sonnet-4-5"

    def describe(self, kind: str, name: str, context: str) -> dict:
        if self.conn is None:
            return TemplateProvider().describe(kind, name, context)
        prompt = (f"Write a one-sentence business description and up to 3 synonyms for the {kind} '{name}' "
                  f"({context}) in a utility semantic layer. Reply as JSON with keys description, synonyms.")
        cur = self.conn.cursor()
        cur.execute("SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)", (self.model, prompt))
        return _parse(cur.fetchone()[0])


class AnthropicProvider:  # pragma: no cover - requires network + key
    name = "anthropic"

    def __init__(self, model: str | None, endpoint: str | None):
        self.model = model or "claude-sonnet-5-5"
        self.endpoint = endpoint or "https://api.anthropic.com/v1/messages"
        self.key = os.environ.get("ANTHROPIC_API_KEY", "")

    def describe(self, kind: str, name: str, context: str) -> dict:
        if not self.key:
            return TemplateProvider().describe(kind, name, context)
        body = json.dumps({"model": self.model, "max_tokens": 300, "messages": [{"role": "user", "content":
                           f"Write a one-sentence business description and up to 3 synonyms for the {kind} '{name}' "
                           f"({context}) in a utility semantic layer. Reply only with JSON: "
                           '{"description": "...", "synonyms": ["..."]}'}]}).encode()
        req = urllib.request.Request(self.endpoint, data=body, headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return _parse("".join(b.get("text", "") for b in data.get("content", [])))


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    return {"description": str(d.get("description", ""))[:500], "synonyms": [str(s) for s in d.get("synonyms", [])][:5]}


def provider(cfg: dict):
    p = cfg["llm"]["provider"]
    if p == "cortex":
        return CortexProvider(cfg["llm"].get("model"))
    if p == "anthropic":
        return AnthropicProvider(cfg["llm"].get("model"), cfg["llm"].get("endpoint"))
    return TemplateProvider()


def draft_suggestions(g: MetaGraph, d: Design, cfg: dict, existing: dict | None = None) -> dict:
    """Return {suggestion_id: {...}} for semantic dimensions and metrics; keeps prior steward decisions."""
    existing = existing or {}
    prov = provider(cfg)
    out = {}
    for sid, sv in sorted(d.semantic_views.items()):
        for kind, fields in (("dimension", sv.dimensions), ("metric", sv.metrics)):
            for f in fields:
                key = f"{sid}.{f.alias}.{f.name}"
                sug_id = stable_hash(key, 16)
                if sug_id in existing and existing[sug_id]["status"] != "suggested":
                    out[sug_id] = existing[sug_id]
                    continue
                res = prov.describe(kind, f.name, f"{sv.name}, table {f.alias}")
                out[sug_id] = {"id": sug_id, "target": key, "kind": kind, "provider": prov.name,
                               "current_description": f.comment, "current_synonyms": f.synonyms,
                               "description": res["description"], "synonyms": res["synonyms"], "status": "suggested"}
    return out


def apply_accepted(d: Design, suggestions: dict) -> int:
    """Merge steward-accepted suggestions into the design (descriptions + synonyms)."""
    n = 0
    index = {}
    for sv in d.semantic_views.values():
        for f in sv.dimensions + sv.metrics:
            index[f"{sv.id}.{f.alias}.{f.name}"] = f
    for s in suggestions.values():
        if s.get("status") != "accepted":
            continue
        f = index.get(s["target"])
        if f is None:
            continue
        if s.get("description"):
            f.comment = s["description"]
        f.synonyms = list(dict.fromkeys(list(f.synonyms) + list(s.get("synonyms", []))))
        n += 1
    return n
