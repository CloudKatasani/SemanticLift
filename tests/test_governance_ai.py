"""Governance-tool metadata (Collibra, Atlan, Alation) and the optional AI advisor."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from semlift.ingest.governance import detect_tool, looks_like_governance, normalise
from semlift.service import ai as aimod
from semlift.service.workspace import Workspace

from .conftest import BUNDLE, ESTATE, ROOT

GOV = ROOT / "samples" / "governance"
SECRET = "sk-test-never-stored-123"


class FakeLLM:
    """Agrees with the rules except for the first report of each batch, which it consolidates."""

    def __init__(self):
        self.calls = []

    def complete_json(self, system, user, schema, name):
        self.calls.append(name)
        if name == "report_reviews":
            batch = json.loads(user.split("Report groups to review:\n", 1)[1])
            sib = json.loads(user.split("consolidate into: ", 1)[1].split("\n", 1)[0])
            reviews = [{"report": r["report"], "recommendation": "Consolidate" if i == 0 else r["rule_recommendation"],
                        "consolidate_into": sib[-1] if sib[-1] != r["report"] else sib[0], "confidence": "medium",
                        "rationale": "same KPIs as a sibling", "business_domain": "Energy"} for i, r in enumerate(batch)]
            reviews.append({"report": "Not A Report", "recommendation": "Keep", "consolidate_into": "", "confidence": "high",
                            "rationale": "", "business_domain": ""})
            return {"reviews": reviews}, {"input_tokens": 100, "output_tokens": 40}
        keys = [p["key"] for p in json.loads(user.split("Proposed data products:\n", 1)[1])]
        return {"products": [{"key": k, "recommended_name": f"{k} product", "description": "d", "owner_suggestion": "o",
                              "boundary_advice": "b", "semantic_layer_advice": "s", "risks": ["r"], "confidence": "high"}
                             for k in keys] + [{"key": "NOPE", "recommended_name": "", "description": "", "owner_suggestion": "",
                                                "boundary_advice": "", "semantic_layer_advice": "", "risks": [], "confidence": "low"}],
                "opportunities": [{"name": "Customer 360", "rationale": "shared customer dimension", "based_on": ["Customer"]}]}, \
            {"input_tokens": 10, "output_tokens": 5}


@pytest.fixture(scope="module")
def gws(tmp_path_factory):
    w = Workspace(tmp_path_factory.mktemp("gov"))
    w.set_config(ESTATE)
    w.run(BUNDLE, extra_sources=sorted(GOV.iterdir()))
    return w


# ------------------------------------------------------------------ adapter
def test_header_detection_per_tool():
    assert detect_tool(["Full Name", "Asset Type", "Community", "Description"], "export.csv") == "collibra"
    assert detect_tool(["qualifiedName", "typeName", "certificateStatus"], "assets.csv") == "atlan"
    assert detect_tool(["key", "title", "otype", "description"], "catalog.json") == "alation"
    assert detect_tool(["Name", "Owner"], "acme_alation_dump.xlsx") == "alation"
    assert looks_like_governance(["Name", "Description", "Owner"])
    assert not looks_like_governance(["ReportName", "RunsPerDay", "Description", "Name"])     # a usage file
    assert not looks_like_governance(["TABLE_NAME", "COLUMN_NAME", "DATA_TYPE"])              # a source catalog


def test_normalise_qualified_names_and_certification():
    a = normalise({"qualifiedName": "default/snowflake/1700000000/ENERGY_DW/BILLING/BILLING/BILL_AMOUNT",
                   "typeName": "Column", "certificateStatus": "DRAFT", "atlanTags": "PII; Confidential"}, "atlan", "x")
    assert (a["asset_type"], a["database"], a["schema"], a["table"], a["column"]) == ("column", "ENERGY_DW", "BILLING", "BILLING", "BILL_AMOUNT")
    assert a["certified"] is False and a["classifications"] == ["PII", "Confidential"]
    c = normalise({"Full Name": "Energy > DW > Customer", "Asset Type": "Table", "Status": "Approved",
                   "Personal Data Classification": "Personal Data (PII)"}, "collibra", "y")
    assert c["asset_type"] == "table" and c["table"] == "Customer" and c["certified"] is True
    assert c["classifications"] == ["Personal Data (PII)"]
    assert normalise({"foo": "bar"}, "generic", "z") is None


def test_governance_files_detected_and_matched(gws):
    st = json.loads((gws.root / "state.json").read_text())
    gov_files = [f for f in st["ingest"]["files"] if f["adapter"] == "GOV"]
    assert len(gov_files) == 3 and all(f["records"] > 0 for f in gov_files)
    g = gws.view("governance")
    assert g["loaded"] and g["tools"] == {"collibra": 15, "atlan": 10, "alation": 5}
    assert g["matched"]["tables"] >= 6 and g["matched"]["columns"] >= 10 and g["matched"]["terms"] >= 3
    assert "governance" in st and "items" not in st["governance"]          # the summary stays small


def test_governance_enriches_design_and_findings(gws):
    rows = json.loads((gws.root / "state.json").read_text())["findings"]
    codes = {(f["code"], json.dumps(f)) for f in rows}
    assert any(c == "F22" and "CustomerName" in (o or "") for c, o in codes)
    assert any(c == "F23" for c, _ in codes)
    products = gws.view("products")["products"]
    billing = next(p for p in products if "Billing" in p["key"])
    assert billing["owner"] == "Maria Lopez"
    assert billing["governance"]["recommendations"]
    ddl = (gws.output / "ddl").rglob("*.sql")
    text = "\n".join(p.read_text() for p in ddl)
    assert "DATA_CLASSIFICATION" in text


def test_run_without_governance_unchanged(tmp_path):
    w = Workspace(tmp_path)
    w.set_config(ESTATE)
    w.run(BUNDLE)
    assert w.view("governance") == {"loaded": False}
    assert all(p["governance"] is None for p in w.view("products")["products"])


# ------------------------------------------------------------------ AI advisor
def test_ai_review_with_fake_provider(gws, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(aimod, "make_client", lambda settings, cfg: fake)
    gws.run_ai({"provider": "anthropic", "model": "claude-opus-5-5", "api_key": SECRET,
                "tasks": ["rationalization", "products"]})
    v = gws.ai_view()
    assert v["status"] == "succeeded" and v["provider"] == "anthropic" and v["model"] == "claude-opus-5-5"
    assert v["governance_used"] is True
    r = v["tasks"]["rationalization"]
    assert r["reviewed"] > 50 and r["disagree"] >= 1 and r["agree"] + r["disagree"] == r["reviewed"]
    assert "Not A Report" not in v["reports"]                              # invented names are dropped
    for name, rv in v["reports"].items():
        if rv["recommendation"] == "Consolidate":
            assert rv["consolidate_into"] and rv["consolidate_into"] != name
    assert "NOPE" not in v["products"] and v["products"]
    assert v["opportunities"][0]["name"] == "Customer 360"
    assert v["usage"]["requests"] == len(fake.calls)
    for p in gws.root.rglob("*"):                                           # the key is never written anywhere
        if p.is_file() and p.stat().st_size < 20_000_000:
            assert SECRET.encode() not in p.read_bytes(), p


def test_ai_errors_become_a_failed_view(gws, monkeypatch):
    def boom(settings, cfg):
        raise aimod.AIError("The Anthropic API key was rejected")
    monkeypatch.setattr(aimod, "make_client", boom)
    gws.run_ai({"provider": "anthropic", "api_key": "bad"})
    v = gws.ai_view()
    assert v["status"] == "failed" and "rejected" in v["error"]


def test_missing_key_and_unknown_provider(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(aimod.AIError):
        aimod.make_client({"provider": "anthropic"}, {})
    with pytest.raises(aimod.AIError):
        aimod.make_client({"provider": "nope", "api_key": "k"}, {})
    with pytest.raises(aimod.AIError):
        aimod.make_client({"provider": "openai_compatible", "api_key": "k", "model": "m", "base_url": "ftp://x"}, {})
    pub = aimod.providers_public()
    assert pub["anthropic"]["default_model"] == "claude-opus-5-5" and "key_env" not in pub["anthropic"]


class _Mock(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Mock.seen.append((self.headers["Authorization"], body))
        if body["response_format"]["type"] == "json_schema":        # behave like an endpoint without JSON-schema output
            msg = b'{"error": "response_format json_schema is not supported"}'
            self.send_response(400)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        out = json.dumps({"choices": [{"message": {"content": json.dumps({"ok": True})}}],
                          "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_openai_compatible_endpoint_with_json_object_fallback():
    srv = HTTPServer(("127.0.0.1", 0), _Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        llm = aimod.make_client({"provider": "openai_compatible", "model": "local-model", "api_key": "k1",
                                 "base_url": f"http://127.0.0.1:{srv.server_port}/v1"}, {})
        out, usage = llm.complete_json("sys", "user", {"type": "object"}, "t")
        assert out == {"ok": True} and usage == {"input_tokens": 7, "output_tokens": 3}
        assert [b["response_format"]["type"] for _, b in _Mock.seen] == ["json_schema", "json_object"]
        assert _Mock.seen[0][0] == "Bearer k1"
    finally:
        srv.shutdown()


# ------------------------------------------------------------------ API
@pytest.fixture()
def client(tmp_path, monkeypatch):
    for k in ("SEMLIFT_WORKSPACE", "SEMLIFT_API_TOKEN", "SEMLIFT_TRUST_PROXY_HEADERS", "SEMLIFT_USERS_FILE",
              "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SEMLIFT_HOME", str(tmp_path / "home"))
    import semlift.api.app as appmod
    return TestClient(appmod.app), tmp_path


def _wait(c, H, jid):
    for _ in range(480):
        j = c.get(f"/api/jobs/{jid}", headers=H).json()
        if j["status"] in ("succeeded", "failed"):
            return j
        time.sleep(0.25)
    raise AssertionError("job did not finish")


def test_api_run_with_and_without_ai(client, monkeypatch):
    c, tmp = client
    monkeypatch.setattr(aimod, "make_client", lambda settings, cfg: FakeLLM())
    pid = c.post("/api/projects", json={"name": "AI"}).json()["id"]
    H = {"X-SemLift-Project": pid}
    prov = c.get("/api/ai/providers", headers=H).json()
    assert set(prov) == {"anthropic", "openai", "openai_compatible"} and prov["anthropic"]["server_key"] is False
    files = [("files", (BUNDLE.name, BUNDLE.read_bytes(), "application/zip"))]
    files += [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in sorted(GOV.iterdir())]
    assert c.post("/api/uploads", headers=H, files=files).status_code == 200
    assert c.post("/api/jobs/run", headers=H, json={"config": "energy_estate", "ai": {"provider": "bogus"}}).status_code == 400
    j = c.post("/api/jobs/run", headers=H, json={"config": "energy_estate", "ai": {
        "provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": SECRET, "tasks": ["rationalization"]}}).json()
    j = _wait(c, H, j["id"])
    assert j["status"] == "succeeded", j
    assert j["result"]["ai"]["status"] == "succeeded" and j["result"]["ai"]["model"] == "claude-sonnet-5-5"
    assert SECRET not in json.dumps(j)
    v = c.get("/api/ai", headers=H).json()
    assert v["reports"] and not v["products"]                    # only the requested task ran
    assert c.get("/api/ingest", headers=H).json()["governance"]["loaded"] is True
    audit = c.get("/api/audit?limit=500", headers=H).json()["entries"]
    run_entry = next(e for e in audit if e["action"].startswith("pipeline."))
    assert "claude-sonnet-5-5" in json.dumps(run_entry) and SECRET not in json.dumps(audit)
    # AI review only, keeping the run
    j = _wait(c, H, c.post("/api/jobs/ai", headers=H, json={"provider": "anthropic", "api_key": SECRET,
                                                            "tasks": ["products"]}).json()["id"])
    assert j["status"] == "succeeded" and c.get("/api/ai", headers=H).json()["products"]
    # a run without AI drops the previous AI review
    j = _wait(c, H, c.post("/api/jobs/run", headers=H, json={"config": "energy_estate"}).json()["id"])
    assert j["status"] == "succeeded" and j["result"].get("ai") is None
    assert c.get("/api/ai", headers=H).json() == {"status": "none"}
    home = tmp / "home"
    for p in home.rglob("*"):
        if p.is_file() and p.stat().st_size < 20_000_000:
            assert SECRET.encode() not in p.read_bytes(), p
