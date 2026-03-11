import os
import subprocess
from pathlib import Path

import pytest
import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
A_BASE = os.getenv("A_BASE_URL", "http://localhost:8002")
D_BASE = os.getenv("D_BASE_URL", "http://localhost:8010")


def _run_p0_smoke_once() -> None:
    script = ROOT_DIR / "script" / "p0_smoke_check.sh"
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "p0_smoke_check failed\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )


@pytest.fixture(scope="session", autouse=True)
def prepared_env():
    # Make tests self-contained: ensure one valid reconstructed round exists.
    if os.getenv("SKIP_P0_PREPARED", "0") == "1":
        yield
        return
    _run_p0_smoke_once()
    yield


@pytest.fixture()
def a_base_url() -> str:
    return A_BASE


@pytest.fixture()
def d_base_url() -> str:
    return D_BASE


def get_json(url: str):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def post_json(url: str):
    r = requests.post(url, timeout=10)
    r.raise_for_status()
    return r.json()
