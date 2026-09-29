"""commit-confirmed auto-rollback test against the real vSRX lab.

Loads a marker policy on slave-1, commits with a 1-minute confirm window, then
does NOT call confirm(). Waits ~75 seconds and verifies the change is gone.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from jnpr.junos import Device
from lxml import etree

from srxsync.categories import CategoryModel
from srxsync.inventory import load_inventory
from tests.integration.conftest import LAB_FILE

MARKER = "srxsync-rollback-marker"


def _slave_has_policy(host, user, key, name):
    filt = etree.fromstring(
        "<configuration><security><policies/></security></configuration>"
    )
    with Device(host=host, user=user, ssh_private_key_file=key, normalize=True) as dev:
        resp = dev.rpc.get_config(filter_xml=filt)
    return name in etree.tostring(resp).decode()


@pytest.mark.slow
def test_commit_confirmed_auto_rollback(lab, transport_cls):
    cats = CategoryModel.default()
    inv = load_inventory(LAB_FILE, known_categories=cats.known_names())
    slave1 = inv.targets[0].host
    user = os.environ.get("SRXSYNC_LAB_USER", "srxsync")
    key = os.environ.get(
        "SRXSYNC_LAB_SSH_KEY", str(Path.home() / ".ssh" / "id_ed25519")
    )

    payload = etree.fromstring(f"""
      <configuration>
        <security>
          <policies>
            <policy>
              <from-zone-name>trust</from-zone-name>
              <to-zone-name>trust</to-zone-name>
              <policy>
                <name>{MARKER}</name>
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
    """)

    t = transport_cls()
    try:
        t.connect(slave1, user, None, ssh_key=key)
        t.load(payload, mode="merge")
        t.commit_confirmed(1)  # 1-minute window, we will NOT confirm
    finally:
        # Close without confirm(). The commit stays pending; Junos will roll it
        # back on its own once the 1-minute timer lapses.
        t.close()

    # Wait past the 1-minute window plus a cushion for Junos to apply rollback.
    time.sleep(75)

    assert not _slave_has_policy(slave1, user, key, MARKER), (
        "commit confirmed did not auto-rollback after window expired"
    )
