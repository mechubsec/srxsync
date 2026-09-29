"""End-to-end push tests against the real vSRX lab.

Uses only the `policies` category (per tests/lab.yaml) to avoid disturbing
zone-to-interface bindings that would sever SSH on the slaves.
"""

from __future__ import annotations

import asyncio

import pytest
from jnpr.junos import Device
from jnpr.junos.utils.config import Config
from lxml import etree

from srxsync.categories import CategoryModel
from srxsync.inventory import load_inventory
from srxsync.orchestrator import Orchestrator, RunConfig
from tests.integration.conftest import LAB_FILE

DRIFT_POLICY_NAME = "srxsync-drift-marker"


def _slave_device(host, user, key):
    return Device(host=host, user=user, ssh_private_key_file=key, normalize=True)


def _set_drift_policy(host, user, key):
    """Add a marker policy on the slave that the master does NOT have."""
    snippet = f"""
    <configuration>
      <security>
        <policies>
          <policy>
            <from-zone-name>trust</from-zone-name>
            <to-zone-name>trust</to-zone-name>
            <policy>
              <name>{DRIFT_POLICY_NAME}</name>
              <match>
                <source-address>any</source-address>
                <destination-address>any</destination-address>
                <application>any</application>
              </match>
              <then><deny/></then>
            </policy>
          </policy>
        </policies>
      </security>
    </configuration>
    """
    with _slave_device(host, user, key) as dev:
        cfg = Config(dev, mode="exclusive")
        cfg.lock()
        try:
            cfg.load(etree.tostring(etree.fromstring(snippet)).decode(),
                     format="xml", action="merge", ignore_warning=True)
            cfg.commit()
        finally:
            cfg.unlock()


def _slave_has_policy(host, user, key, name):
    filt = etree.fromstring(
        "<configuration><security><policies/></security></configuration>"
    )
    with _slave_device(host, user, key) as dev:
        resp = dev.rpc.get_config(filter_xml=filt)
    return name in etree.tostring(resp).decode()


@pytest.fixture
def lab_ctx(lab, transport_cls):
    cats = CategoryModel.default()
    inv = load_inventory(LAB_FILE, known_categories=cats.known_names())
    orch = Orchestrator(inv, cats, transport_factory=transport_cls)
    import os
    from pathlib import Path

    user = os.environ.get("SRXSYNC_LAB_USER", "srxsync")
    key = os.environ.get(
        "SRXSYNC_LAB_SSH_KEY", str(Path.home() / ".ssh" / "id_ed25519")
    )
    return {"orch": orch, "inv": inv, "user": user, "key": key}


def test_replace_wipes_slave_specific_policy(lab_ctx):
    """Inject drift on slave-1, --replace from master, verify drift is gone."""
    slave1 = lab_ctx["inv"].targets[0].host
    user, key = lab_ctx["user"], lab_ctx["key"]

    _set_drift_policy(slave1, user, key)
    assert _slave_has_policy(slave1, user, key, DRIFT_POLICY_NAME), (
        "failed to seed drift policy on slave-1"
    )

    cfg = RunConfig(
        mode="replace",
        commit_confirmed_minutes=2,
        max_parallel=2,
        on_error="continue",
    )
    push = asyncio.run(lab_ctx["orch"].push(cfg))
    assert push.all_ok, (
        f"push failed: {[(r.host, r.error) for r in push.results if not r.ok]}"
    )
    assert not _slave_has_policy(slave1, user, key, DRIFT_POLICY_NAME), (
        "replace did not wipe slave-specific policy"
    )
