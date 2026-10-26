from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "samples" / "Cognos Lineage Input.zip"
ESTATE = ROOT / "config" / "energy_estate.yaml"


@pytest.fixture(scope="session")
def result(tmp_path_factory):
    from semlift.pipeline import run
    return run(BUNDLE, tmp_path_factory.mktemp("work"), ESTATE)


@pytest.fixture(scope="session")
def graph(result):
    return result.graph


@pytest.fixture(scope="session")
def design(result):
    return result.design
