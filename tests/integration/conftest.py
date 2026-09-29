"""Integration test config — loads tests/lab.yaml or skips the whole module.

Also sets SRX_USER_<HOST> and SRX_SSH_KEY_<HOST> env vars from the lab file
so the env SecretProvider can resolve credentials for each device.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

LAB_FILE = Path(__file__).resolve().parents[1] / "lab.yaml"


def _env_key(prefix: str, host: str) -> str:
    return f"{prefix}_{host.upper().replace('.', '_').replace('-', '_')}"


def pytest_collection_modifyitems(config, items):
    if LAB_FILE.exists():
        return
    skip_lab = pytest.mark.skip(reason=f"lab config missing: {LAB_FILE}")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip_lab)


@pytest.fixture(scope="session")
def lab():
    if not LAB_FILE.exists():
        pytest.skip(f"lab config missing: {LAB_FILE}")
    data = yaml.safe_load(LAB_FILE.read_text())

    user = os.environ.get("SRXSYNC_LAB_USER", "srxsync")
    key = os.environ.get(
        "SRXSYNC_LAB_SSH_KEY",
        str(Path.home() / ".ssh" / "id_ed25519"),
    )

    hosts = [data["source"]["host"]] + [t["host"] for t in data["targets"]]
    for host in hosts:
        os.environ.setdefault(_env_key("SRX_USER", host), user)
        os.environ.setdefault(_env_key("SRX_SSH_KEY", host), key)
    return data


@pytest.fixture(params=["pyez", "rustez"])
def transport_cls(request):
    """Parameterized transport class; skips rustez param when extra missing."""
    name = request.param
    if name == "rustez":
        import importlib.util

        if importlib.util.find_spec("rustez") is None:
            pytest.skip("rustez not installed - run: pip install -e .[rust]")
    from srxsync.transport import make_transport

    return make_transport(name)
