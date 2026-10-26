"""Recursive, isolated archive unpacking and per-file adapter detection (FR-01)."""
from __future__ import annotations

import csv
import io
import os
import shutil
import zipfile
from pathlib import Path

from lxml import etree

MAX_DEPTH = 5
MAX_TOTAL_BYTES = 2 * 1024 ** 3


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> list[Path]:
    out = []
    dest = dest.resolve()
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if name.startswith("__MACOSX/") or Path(name).name.startswith("._"):
            continue
        target = (dest / name).resolve()
        if not str(target).startswith(str(dest) + os.sep):
            raise ValueError(f"Unsafe path in archive: {info.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        out.append(target)
    return out


def unpack(source: str | Path, work_dir: str | Path) -> Path:
    """Copy/unpack ``source`` (zip or folder) into ``work_dir/input``; nested zips are expanded
    in place into ``<name>.zip.d`` folders. Returns the root folder."""
    source = Path(source)
    work = Path(work_dir) / "input"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    if source.is_dir():
        shutil.copytree(source, work, dirs_exist_ok=True)
    elif zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            _safe_extract(zf, work)
    else:
        shutil.copy2(source, work / source.name)
    for _ in range(MAX_DEPTH):
        nested = [p for p in sorted(work.rglob("*.zip")) if p.is_file()]
        if not nested:
            break
        for z in nested:
            d = z.with_name(z.name + ".d")
            with zipfile.ZipFile(z) as zf:
                _safe_extract(zf, d)
            z.unlink()
    total = sum(p.stat().st_size for p in work.rglob("*") if p.is_file())
    if total > MAX_TOTAL_BYTES:
        raise ValueError("Unpacked bundle exceeds size limit")
    return work


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if isinstance(tag, str) else ""


def xml_root_info(path: Path) -> tuple[str, str]:
    """Return (root local name, namespace uri) without loading the whole document."""
    try:
        for _event, elem in etree.iterparse(str(path), events=("start",), resolve_entities=False,
                                            no_network=True, huge_tree=True):
            tag = elem.tag
            ns = tag[1:].split("}", 1)[0] if tag.startswith("{") else (elem.nsmap.get(None) or "")
            return _local(tag), ns
    except etree.XMLSyntaxError:
        return "", ""
    return "", ""


def sheet_headers(path: Path) -> list[list[str]]:
    """First 10 rows of every sheet / CSV, stringified, for header detection."""
    rows: list[list[str]] = []
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= 10:
                    break
                rows.append(["" if v is None else str(v).strip() for v in row])
        wb.close()
    else:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for i, row in enumerate(csv.reader(io.StringIO(fh.read(65536)))):
                if i >= 10:
                    break
                rows.append([c.strip() for c in row])
    return rows


def detect_adapter(path: Path) -> tuple[str, str]:
    """Return (adapter code, detail). Adapter '' means rejected."""
    suffix = path.suffix.lower()
    if suffix in (".xml", ".cpf", ".ns", ".ds"):
        root, ns = xml_root_info(path)
        if not root:
            return "", "not well-formed XML"
        if root == "project" and "/schemas/bmt/60/" in ns:
            return ("FM-PROJ", "cpf") if suffix == ".cpf" else ("FM-PROJ", "model")
        if root == "namespace" and "bmt" in ns:
            return "FM-NS", "namespace summary"
        if root in ("rowLevelSecurity", "objectLevelSecurity"):
            return "FM-SEC", root
        if root == "parameterMap":
            return "FM-PARAM", root
        if root == "dataSourceConnection":
            return "FM-DS", root
        if root == "publishSettings":
            return "FM-PUB", root
        if root in ("contentExport", "report"):
            return "RPT", root
        return "", f"unknown XML root <{root}>"
    if suffix in (".xlsx", ".xlsm", ".csv"):
        try:
            rows = sheet_headers(path)
        except Exception as e:  # pragma: no cover - corrupt workbook
            return "", f"unreadable sheet: {e}"
        for r in rows:
            low = {c.lower() for c in r}
            if "report_name" in low and "runs_per_day" in low:
                return "USAGE", "usage sheet"
            if any(c.lower().startswith("cogipf_") for c in r):
                return "USAGE", "audit extract"
            if "fm package" in low and "source database/system" in low:
                return "MAP", "package mapping"
            if {"table_name", "column_name"} <= low:
                return "SRC-CAT", "catalog csv"
        return "", "no recognised header in first 10 rows"
    return "", f"unsupported file type {suffix or '(none)'}"
