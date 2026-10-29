"""Multi-client projects, identity and roles, audit trail, background runs, governance and config checks."""
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from semlift.config import load_config, validate_config
from semlift.design.naming import package_label
from semlift.service.identity import sha256

from .conftest import BUNDLE, ESTATE

TOKENS = {"ann": "t-admin", "vic": "t-viewer", "sam": "t-steward", "pat": "t-approver"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMLIFT_WORKSPACE", raising=False)
    monkeypatch.delenv("SEMLIFT_API_TOKEN", raising=False)
    monkeypatch.delenv("SEMLIFT_TRUST_PROXY_HEADERS", raising=False)
    monkeypatch.delenv("SEMLIFT_USERS_FILE", raising=False)
    monkeypatch.setenv("SEMLIFT_HOME", str(tmp_path / "home"))
    import semlift.api.app as appmod
    return TestClient(appmod.app), tmp_path


def users_file(tmp_path, monkeypatch, governance=None):
    f = tmp_path / "users.yaml"
    f.write_text(yaml.safe_dump({
        "users": [
            {"name": "Ann Admin", "email": "ann@x.com", "token_sha256": sha256(TOKENS["ann"]), "roles": ["admin"]},
            {"name": "Vic Viewer", "token_sha256": sha256(TOKENS["vic"]), "projects": {"acme-*": ["viewer"]}},
            {"name": "Sam Steward", "token_sha256": sha256(TOKENS["sam"]), "projects": {"acme-*": ["steward", "analyst"]}},
            {"name": "Pat Approver", "token_sha256": sha256(TOKENS["pat"]), "projects": {"*": ["approver"]}},
        ],
        "groups": {"acme-stewards": {"acme-*": ["steward"]}},
    }))
    monkeypatch.setenv("SEMLIFT_USERS_FILE", str(f))


def h(user, project=None):
    out = {"Authorization": f"Bearer {TOKENS[user]}"}
    if project:
        out["X-SemLift-Project"] = project
    return out


def upload_and_run(c, headers):
    assert c.post("/api/uploads", headers=headers,
                  files=[("files", (BUNDLE.name, BUNDLE.read_bytes(), "application/zip"))]).status_code == 200
    r = c.post("/api/run", headers=headers, json={"config": "energy_estate"})
    assert r.status_code == 200, r.text
    return r.json()


def test_projects_are_isolated_and_audited(client):
    c, _ = client
    assert c.get("/api/health").json()["auth_mode"] == "open"
    assert c.get("/api/summary").status_code == 400            # no project selected yet
    a = c.post("/api/projects", json={"name": "Cognos wave 1", "client": "Acme"}).json()
    b = c.post("/api/projects", json={"name": "Finance", "client": "Globex", "config": "energy_estate"}).json()
    assert a["id"] == "acme-cognos-wave-1" and b["id"] == "globex-finance"
    assert c.post("/api/projects", json={"name": "Cognos wave 1", "client": "Acme"}).status_code == 409
    out = upload_and_run(c, {"X-SemLift-Project": a["id"]})
    assert out["config_warnings"] == []
    assert c.get("/api/summary", headers={"X-SemLift-Project": a["id"]}).status_code == 200
    assert c.get("/api/summary", params={"project": b["id"]}).status_code == 404     # nothing leaks across projects
    assert c.get("/api/uploads", params={"project": b["id"]}).json() == []
    cards = {p["id"]: p for p in c.get("/api/projects").json()}
    assert cards[a["id"]]["summary"]["reports"] == 588 and cards[b["id"]]["summary"] is None
    hdr = {"X-SemLift-Project": a["id"], "X-SemLift-User": "maria"}
    assert c.post("/api/portfolio/Outage_Event_Log", headers=hdr, json={"disposition": "Keep"}).status_code == 200
    cards = {p["id"]: p for p in c.get("/api/projects").json()}
    assert cards[a["id"]]["summary"]["report_decisions"] == 1 and cards[a["id"]]["summary"]["pending_rerun"]
    log = c.get("/api/audit", headers={"X-SemLift-Project": a["id"]}).json()
    assert [e["action"] for e in log["entries"]][:3] == ["decision.report", "pipeline.run", "upload.add"]
    assert log["entries"][0]["user"] == "maria" and log["entries"][1]["user"] == "local" and log["entries"][0]["detail"]["disposition"] == "Keep"
    assert c.get("/api/audit", params={"project": b["id"]}).json()["entries"][0]["action"] == "project.create"
    # archived projects are read-only and hidden by default
    c.patch(f"/api/projects/{b['id']}", json={"status": "archived"})
    assert b["id"] not in {p["id"] for p in c.get("/api/projects").json()}
    assert c.post("/api/uploads", params={"project": b["id"]},
                  files=[("files", ("x.csv", b"a,b", "text/csv"))]).status_code == 409


def test_roles_and_identity(client, monkeypatch):
    c, tmp = client
    users_file(tmp, monkeypatch)
    assert c.get("/api/projects").status_code == 401
    assert c.get("/api/projects", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post("/api/projects", headers=h("sam"), json={"name": "x"}).status_code == 403
    pid = c.post("/api/projects", headers=h("ann"), json={"name": "Wave 1", "client": "Acme"}).json()["id"]
    other = c.post("/api/projects", headers=h("ann"), json={"name": "Other", "client": "Globex"}).json()["id"]
    assert {p["id"] for p in c.get("/api/projects", headers=h("sam")).json()} == {pid}
    assert c.get("/api/summary", headers=h("sam", other)).status_code == 404          # cannot see other clients
    assert c.post("/api/uploads", headers=h("vic", pid),
                  files=[("files", ("x.csv", b"a", "text/csv"))]).status_code == 403
    upload_and_run(c, h("sam", pid))
    assert c.get("/api/me", headers=h("vic", pid)).json()["roles"] == ["viewer"]
    assert c.post("/api/portfolio/Outage_Event_Log", headers=h("vic", pid), json={"disposition": "Keep"}).status_code == 403
    r = c.post("/api/portfolio/Outage_Event_Log", headers=h("sam", pid),
               json={"disposition": "Keep", "reviewer": "someone else"}).json()
    assert r["decision"]["reviewer"] == "Sam Steward"                                 # identity, not the request body
    assert c.post("/api/objects/CORE.DIM_DATE/review", headers=h("sam", pid), json={"action": "approve"}).status_code == 403
    o = c.post("/api/objects/CORE.DIM_DATE/review", headers=h("pat", pid), json={"action": "approve"}).json()
    assert o["review"]["reviewer"] == "Pat Approver"
    assert c.post("/api/deploy", headers=h("pat", pid), json={}).status_code == 403
    users = {e["user"] for e in c.get("/api/audit", headers=h("vic", pid)).json()["entries"]}
    assert users == {"Ann Admin", "Sam Steward", "Pat Approver"}


def test_sso_proxy_headers(client, monkeypatch):
    c, tmp = client
    users_file(tmp, monkeypatch)
    pid = c.post("/api/projects", headers=h("ann"), json={"name": "Wave 1", "client": "Acme"}).json()["id"]
    sso = {"X-Forwarded-Email": "lee@acme.com", "X-Forwarded-User": "lee", "X-Forwarded-Groups": "staff,acme-stewards"}
    assert c.get("/api/projects", headers=sso).status_code == 401                     # headers ignored unless trusted
    monkeypatch.setenv("SEMLIFT_TRUST_PROXY_HEADERS", "1")
    me = c.get("/api/me", headers=sso | {"X-SemLift-Project": pid}).json()
    assert me["name"] == "lee" and me["auth_mode"] == "proxy" and me["roles"] == ["viewer", "steward"]
    known = c.get("/api/me", headers={"X-Forwarded-Email": "ann@x.com"}).json()
    assert known["name"] == "Ann Admin" and known["admin"]


def test_background_run_and_four_eyes(client):
    c, tmp = client
    cfg = tmp / "four_eyes.yaml"
    cfg.write_text(ESTATE.read_text() + "\ngovernance:\n  four_eyes: true\n")
    import semlift.api.app as appmod
    appmod.CONFIG_DIR = tmp
    try:
        pid = c.post("/api/projects", json={"name": "Jobs"}).json()["id"]
        H = {"X-SemLift-Project": pid}
        assert c.post("/api/jobs/run", headers=H, json={}).status_code == 400          # nothing uploaded
        c.post("/api/uploads", headers=H, files=[("files", (BUNDLE.name, BUNDLE.read_bytes(), "application/zip"))])
        j = c.post("/api/jobs/run", headers=H, json={"config": "four_eyes"}).json()
        assert j["status"] in ("queued", "running")
        assert c.post("/api/jobs/run", headers=H, json={}).status_code == 409           # one run per project
        for _ in range(240):
            j = c.get(f"/api/jobs/{j['id']}", headers=H).json()
            if j["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.25)
        assert j["status"] == "succeeded", j
        assert j["result"]["objects"] > 100
        ddl = c.get("/api/objects/CORE.DIM_DATE", headers=H).json()["ddl"]
        ed = {"action": "edit", "ddl": ddl + "\n-- reviewed"}
        assert c.post("/api/objects/CORE.DIM_DATE/review", headers=H | {"X-SemLift-User": "maria"}, json=ed).status_code == 200
        r = c.post("/api/objects/CORE.DIM_DATE/review", headers=H | {"X-SemLift-User": "maria"}, json={"action": "approve"})
        assert r.status_code == 409 and "four-eyes" in r.json()["detail"]
        assert c.post("/api/objects/CORE.DIM_DATE/review", headers=H | {"X-SemLift-User": "omar"},
                      json={"action": "approve"}).json()["status"] == "approved"
    finally:
        from pathlib import Path
        appmod.CONFIG_DIR = Path(appmod.ROOT / "config")


def test_config_validation_and_neutral_naming():
    assert validate_config(load_config(ESTATE)) == []
    w = validate_config(load_config(None, {"rationalisation": {}, "aggregates": {"max_per_fact": "3"}, "governance": {"four_eyes": "y"}}))
    assert "unknown setting 'rationalisation' (ignored)" in w
    assert "'aggregates.max_per_fact' should be a number" in w and "'governance.four_eyes' should be true or false" in w
    assert package_label("Energy_Billing_Package") == "Energy_Billing"
    assert package_label("Energy_Billing_Package", load_config(ESTATE)) == "Billing"
    assert package_label("Sales_Package") == "Sales"
