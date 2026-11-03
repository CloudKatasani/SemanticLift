"""Demo server with a scripted AI provider, so the walkthrough video can show "Run with AI" without an API key.

    python scripts/demo/demo_ai.py PORT        (used by record_demo.sh)

The scripted provider answers from the metadata it is sent, deterministically: it agrees with the rules except for
low-usage Review reports (suggests Retire) and live reports whose KPIs are all covered by a busier sibling (suggests
Consolidate), and writes product advice from the governance block. The video caption says the AI output is
illustrative. Never use this outside the demo recording.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from semlift.service import ai as aimod  # noqa: E402


class ScriptedLLM:
    def complete_json(self, system: str, user: str, schema: dict, name: str):
        if name == "report_reviews":
            return self._reports(user), {"input_tokens": len(user) // 4, "output_tokens": 900}
        return self._products(user), {"input_tokens": len(user) // 4, "output_tokens": 1400}

    @staticmethod
    def _reports(user: str) -> dict:
        batch = json.loads(user.split("Report groups to review:\n", 1)[1])
        out = []
        for r in batch:
            rec, target, conf = r["rule_recommendation"], r.get("rule_consolidate_into", ""), "high"
            why = f"Agrees with the rules: {r['rule_reasons'][0]}" if r["rule_reasons"] else "Agrees with the rules."
            if rec == "Review" and (r["runs_per_day"] or 0) < 0.5:
                rec, conf = "Retire", "medium"
                usage = ("It has not run in the look-back window" if not r["runs_per_day"]
                         else f"It runs about {r['runs_per_day']:g} times a day")
                content = (f"its {len(r['kpis'])} KPIs are all available in other live reports" if r["kpis"]
                           else "it is a plain list with no KPIs of its own")
                why = (f"{usage} and {content}, so the open review item is not worth migrating it for. "
                       "Confirm with the business owner before retiring it.")
            elif rec == "Keep":
                bigger = [s for s in batch if s["report"] != r["report"] and s["rule_recommendation"] == "Keep"
                          and r["kpis"] and set(r["kpis"]) <= set(s["kpis"]) and s["runs_per_day"] > r["runs_per_day"]]
                if bigger:
                    rec, target, conf = "Consolidate", bigger[0]["report"], "medium"
                    why = (f"Every KPI it shows is also in {target}, which runs more often; its extra dimensions can be "
                           "added there as a filter, leaving one governed report.")
            out.append({"report": r["report"], "recommendation": rec, "consolidate_into": target if rec == "Consolidate" else "",
                        "confidence": conf, "rationale": why, "business_domain": r["report"].split("_")[0]})
        return {"reviews": out}

    @staticmethod
    def _products(user: str) -> dict:
        products = json.loads(user.split("Proposed data products:\n", 1)[1])
        out = []
        for p in products:
            g = p.get("governance") or {}
            metrics = [m for s in p["semantic_views"] for m in s["metrics"]][:3]
            domains = list((g.get("domains") or {}).keys())
            risks = []
            if g.get("unmasked_sensitive"):
                risks.append(f"Sensitive columns without masking: {', '.join(g['unmasked_sensitive'][:3])}.")
            if g.get("uncertified"):
                risks.append(f"Uncertified in the governance tool: {', '.join(g['uncertified'])}.")
            if g and g.get("glossary_coverage_pct", 100) < 50:
                risks.append(f"Only {g['glossary_coverage_pct']}% glossary coverage: natural-language questions will miss business terms.")
            if not risks:
                risks.append("No governance metadata for its tables yet; owners and definitions are inferred from Cognos.")
            out.append({
                "key": p["key"], "recommended_name": p["name"],
                "description": "Conformed reference dimensions shared by every other data product." if not p["semantic_views"] else
                               (f"Governed {p['name'].lower()} figures"
                                + (f" ({', '.join(metrics)})" if metrics else "")
                                + f" for the {p['reports'].get('Keep', 0) + p['reports'].get('Review', 0)} report intents that remain."),
                "owner_suggestion": (f"{(g.get('owners') or [p['owner']])[0]}, as listed in the governance tool"
                                     if g.get("owners") else f"{p['owner']} (no owner recorded in the governance tool)"),
                "boundary_advice": (f"Spans the governance domains {' and '.join(domains)}; keep it as one product only if one "
                                    "team owns both, otherwise publish the shared dimension from Enterprise Reference."
                                    if len(domains) > 1 else "The boundary matches one business domain; keep it as proposed."),
                "semantic_layer_advice": ("Add the glossary terms as synonyms and verified questions for the busiest reports, "
                                          "so analysts can ask for these metrics in business language."),
                "risks": risks, "confidence": "medium" if len(domains) > 1 else "high"})
        return {"products": out, "opportunities": [
            {"name": "Customer 360", "rationale": "Customer appears in billing, service and compliance products with the same "
                                                  "owner; a shared customer product would remove three copies of the dimension.",
             "based_on": ["Customer", "Billing", "ServiceRequest"]}]}


if __name__ == "__main__":
    aimod.make_client = lambda settings, cfg: ScriptedLLM()
    import uvicorn
    uvicorn.run("semlift.api.app:app", host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
