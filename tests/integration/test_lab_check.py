"""Drift detection against the real vSRX lab.

Prereqs (see conftest.py): tests/lab.yaml exists, SSH key auth to master + slaves
works as user `srxsync` (override via SRXSYNC_LAB_USER / SRXSYNC_LAB_SSH_KEY).
"""

from __future__ import annotations

import asyncio

import pytest

from srxsync.categories import CategoryModel
from srxsync.inventory import load_inventory
from srxsync.orchestrator import Orchestrator, RunConfig
from tests.integration.conftest import LAB_FILE


@pytest.fixture
def orch(lab, transport_cls):
    cats = CategoryModel.default()
    inv = load_inventory(LAB_FILE, known_categories=cats.known_names())
    return Orchestrator(inv, cats, transport_factory=transport_cls)


def test_check_runs_and_returns_a_line_per_target(orch, lab):
    summary = asyncio.run(orch.check(max_parallel=2))
    hosts_reported = {line.host for line in summary.reports}
    expected = {t["host"] for t in lab["targets"]}
    assert hosts_reported == expected


def test_merge_then_check_is_in_sync(orch):
    # Ensure slaves match master by merge-pushing first, then re-check.
    cfg = RunConfig(
        mode="merge",
        commit_confirmed_minutes=2,
        max_parallel=2,
        on_error="continue",
    )
    push = asyncio.run(orch.push(cfg))
    assert push.all_ok, f"push failed: {[(r.host, r.error) for r in push.results if not r.ok]}"

    drift = asyncio.run(orch.check(max_parallel=2))
    assert drift.all_in_sync, (
        "slaves drifted after merge push: "
        f"{[(d.host, d.differing_paths, d.error) for d in drift.reports if not d.in_sync]}"
    )
