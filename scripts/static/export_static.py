"""Build the read-only static showcase of SemanticLift (no server needed; host it on S3 or any web server).

    python scripts/static/export_static.py [OUT_DIR]          # default: dist-static/

1. runs the bundled sample estate through the real API, in-process, on a throw-away project home;
2. saves the response of every request the UI makes as data/<path>.json (and the downloads as files);
3. builds the UI with VITE_STATIC=1, which reads those files and refuses changes with a read-only notice.

See docs/DEPLOY_AWS_S3_STATIC.md for publishing the result to an S3 bucket.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "samples" / "Cognos Lineage Input.zip"
CONFIG = "energy_estate"


def slug(url: str) -> str:
    """Same rule as staticPath() in ui/src/api.js: '/api/objects/CORE.X?y' -> 'objects__CORE.X'."""
    path = url.split("?")[0].removeprefix("/api/")
    return "__".join(unquote(p) for p in path.split("/"))


def main(out: Path) -> None:
    home = Path(tempfile.mkdtemp(prefix="semlift-static-"))
    for k in ("SEMLIFT_WORKSPACE", "SEMLIFT_USERS_FILE", "SEMLIFT_API_TOKEN", "SEMLIFT_TRUST_PROXY_HEADERS"):
        os.environ.pop(k, None)
    os.environ["SEMLIFT_HOME"] = str(home)
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    import semlift.api.app as appmod
    c = TestClient(appmod.app)

    pid = c.post("/api/projects", json={"name": "Cognos wave 1", "client": "Northwind Energy", "config": CONFIG,
                                        "description": "Showcase run on the bundled sample estate"}).json()["id"]
    H = {"X-SemLift-Project": pid}
    c.post("/api/uploads", headers=H, files=[("files", (BUNDLE.name, BUNDLE.read_bytes(), "application/zip"))])
    r = c.post("/api/run", headers=H, json={"config": CONFIG})
    r.raise_for_status()
    print(f"run {r.json()['run_id']}: {r.json()['objects']} objects")

    data = out / "data"
    if out.exists():
        shutil.rmtree(out)
    data.mkdir(parents=True)

    def get(url: str):
        resp = c.get(url, headers=H)
        resp.raise_for_status()
        return resp

    def save_json(url: str, payload) -> None:
        (data / f"{slug(url)}.json").write_text(json.dumps(payload, separators=(",", ":"), default=str), encoding="utf-8")

    pages = ["/api/summary", "/api/story", "/api/configs", "/api/uploads", "/api/ingest", "/api/model", "/api/logical-model",
             "/api/lineage", "/api/portfolio", "/api/kpis", "/api/sources", "/api/products-view", "/api/objects-lineage",
             "/api/findings", "/api/objects", "/api/suggestions", "/api/aggregates", "/api/products", "/api/diff",
             "/api/deploy", "/api/jobs"]
    for url in pages:
        save_json(url, get(url).json())
    save_json("/api/audit", get("/api/audit?limit=2000").json())
    # visitors are read-only viewers, whatever the export ran as
    me = get("/api/me").json() | {"name": "Demo visitor", "auth_mode": "static", "admin": False, "roles": ["viewer"]}
    save_json("/api/me", me)
    save_json("/api/projects", [p | {"my_roles": ["viewer"]} for p in get("/api/projects").json()])
    for o in get("/api/objects").json()["objects"]:
        save_json(f"/api/objects/{o['id']}", get(f"/api/objects/{o['id']}").json())
    files = ["traceability.csv", "lineage.json"] + [p["contract"] for p in get("/api/products-view").json()["products"]]
    for rel in files:
        (data / slug(f"/api/files/{rel}")).write_bytes(get(f"/api/files/{rel}").content)
    for name in ("package", "workbook", "findings"):
        (data / slug(f"/api/download/{name}")).write_bytes(get(f"/api/download/{name}").content)

    # the UI, built in static mode with relative asset paths so it also works under a bucket prefix
    ui = ROOT / "ui"
    env = os.environ | {"VITE_STATIC": "1"}
    subprocess.run(["npm", "run", "build", "--", "--base=./", f"--outDir={out.resolve() / '_ui'}", "--emptyOutDir"],
                   cwd=ui, env=env, check=True)
    for p in (out / "_ui").iterdir():
        shutil.move(str(p), out / p.name)
    (out / "_ui").rmdir()
    shutil.rmtree(home, ignore_errors=True)
    n = sum(1 for _ in data.iterdir())
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6
    print(f"static showcase: {out} ({n} data files, {size:.1f} MB)")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "dist-static"))
