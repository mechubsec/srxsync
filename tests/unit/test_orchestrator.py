from __future__ import annotations

import asyncio
from typing import ClassVar, Literal

from lxml import etree

from srxsync.categories import Category, CategoryModel
from srxsync.inventory import Auth, Device, Inventory, Target
from srxsync.orchestrator import Orchestrator, RunConfig
from srxsync.secrets.base import Secret, SecretError
from srxsync.transport.base import Transport


class _LockError(Exception):
    """Stands in for jnpr.junos.exception.LockError — not a TransportError."""


class _FakeTransport(Transport):
    """Per-target behavior is driven by class-level maps keyed on host,
    reset by each test via `reset()`."""

    connect_failures: ClassVar[dict[str, Exception]] = {}
    rollbacks: ClassVar[list[str]] = []
    closes: ClassVar[list[str]] = []

    def __init__(self) -> None:
        self._host = ""
        # Mirrors PyEZTransport, where rollback()/close() are guarded on
        # self._cfg/self._dev — both unset until connect() is at least
        # attempted, so a secret-resolution failure (which never reaches
        # connect()) has nothing to safely roll back.
        self._touched = False

    @classmethod
    def reset(cls, connect_failures: dict[str, Exception] | None = None) -> None:
        cls.connect_failures = connect_failures or {}
        cls.rollbacks = []
        cls.closes = []

    def connect(
        self,
        host: str,
        username: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 22,
    ) -> None:
        self._host = host
        self._touched = True
        failure = self.connect_failures.get(host)
        if failure is not None:
            raise failure

    def fetch(self, paths: list[str]) -> etree._Element:
        return etree.Element("configuration")

    def load(self, xml: etree._Element, mode: Literal["replace", "merge"]) -> None:
        pass

    def commit_confirmed(self, minutes: int) -> None:
        pass

    def confirm(self) -> None:
        pass

    def rollback(self) -> None:
        if self._touched:
            self.rollbacks.append(self._host)

    def close(self) -> None:
        if self._touched:
            self.closes.append(self._host)


def _categories() -> CategoryModel:
    return CategoryModel(
        {
            "objects": Category(
                name="objects",
                paths=("/configuration/security/address-book",),
                prune=(),
            )
        }
    )


def _inventory(hosts: list[str]) -> Inventory:
    return Inventory(
        source=Device(host="198.51.100.1", auth=Auth(provider="env")),
        targets=[Target(host=h, auth=Auth(provider="env"), include=["objects"]) for h in hosts],
    )


def _patch_get_secret(monkeypatch, secret_failures: set[str]) -> None:
    def fake_get_secret(host: str, auth: Auth) -> Secret:
        if host in secret_failures:
            raise SecretError("VAULT_ADDR and VAULT_TOKEN env vars required")
        return Secret(username="svc", password="FAKEPASS")

    monkeypatch.setattr("srxsync.orchestrator.get_secret", fake_get_secret)


HOST_LOCK = "203.0.113.10"
HOST_TIMEOUT = "203.0.113.11"
HOST_VAULT = "203.0.113.12"
HOST_OK = "203.0.113.13"


def test_mixed_lock_timeout_vault_failures_report_every_target_and_roll_back(monkeypatch):
    _FakeTransport.reset(
        connect_failures={
            HOST_LOCK: _LockError("lock held by another NETCONF session"),
            HOST_TIMEOUT: TimeoutError("rpc timed out after 30s"),
        }
    )
    _patch_get_secret(monkeypatch, secret_failures={HOST_VAULT})

    inv = _inventory([HOST_LOCK, HOST_TIMEOUT, HOST_VAULT, HOST_OK])
    orch = Orchestrator(inventory=inv, categories=_categories(), transport_factory=_FakeTransport)
    cfg = RunConfig(mode="merge", commit_confirmed_minutes=1, max_parallel=4, on_error="continue")

    summary = asyncio.run(orch.push(cfg))

    by_host = {r.host: r for r in summary.results}
    # Every target gets a report — none silently dropped by an aborted gather.
    assert set(by_host) == {HOST_LOCK, HOST_TIMEOUT, HOST_VAULT, HOST_OK}

    assert by_host[HOST_LOCK].ok is False
    assert "lock" in by_host[HOST_LOCK].error.lower()
    assert by_host[HOST_TIMEOUT].ok is False
    assert "timed out" in by_host[HOST_TIMEOUT].error.lower()
    assert by_host[HOST_VAULT].ok is False
    assert "vault" in by_host[HOST_VAULT].error.lower()
    assert by_host[HOST_OK].ok is True

    # Rollback runs where applicable — a device-side session was actually
    # touched (connect succeeded far enough to hit lock/timeout). The Vault
    # failure never reached the device, so there is nothing to roll back.
    assert set(_FakeTransport.rollbacks) == {HOST_LOCK, HOST_TIMEOUT}


def test_check_mixed_failures_report_every_target(monkeypatch):
    _FakeTransport.reset(
        connect_failures={
            HOST_LOCK: _LockError("lock held by another NETCONF session"),
            HOST_TIMEOUT: TimeoutError("rpc timed out after 30s"),
        }
    )
    _patch_get_secret(monkeypatch, secret_failures={HOST_VAULT})

    inv = _inventory([HOST_LOCK, HOST_TIMEOUT, HOST_VAULT, HOST_OK])
    orch = Orchestrator(inventory=inv, categories=_categories(), transport_factory=_FakeTransport)

    summary = asyncio.run(orch.check(max_parallel=4))

    by_host = {line.host: line for line in summary.reports}
    assert set(by_host) == {HOST_LOCK, HOST_TIMEOUT, HOST_VAULT, HOST_OK}
    assert by_host[HOST_LOCK].in_sync is False
    assert by_host[HOST_LOCK].error is not None
    assert by_host[HOST_TIMEOUT].error is not None
    assert by_host[HOST_VAULT].error is not None
    assert by_host[HOST_OK].error is None
    assert by_host[HOST_OK].in_sync is True


def test_gather_return_exceptions_defends_against_an_escaped_error(monkeypatch):
    """Even if some future failure mode slips past the per-target except
    clause entirely, the batch must not abort — every target still gets a
    report. This is the return_exceptions=True safety net, exercised
    directly against an exception raised outside of _push_target's own
    try/except."""
    _FakeTransport.reset()
    _patch_get_secret(monkeypatch, secret_failures=set())

    inv = _inventory([HOST_OK, "203.0.113.14"])
    orch = Orchestrator(inventory=inv, categories=_categories(), transport_factory=_FakeTransport)
    cfg = RunConfig(mode="merge", commit_confirmed_minutes=1, max_parallel=4, on_error="continue")

    real_push_target = orch._push_target

    def flaky_push_target(target, source_xml, run_cfg, abort_event):
        if target.host == "203.0.113.14":
            raise RuntimeError("unexpected failure outside the per-target handler")
        return real_push_target(target, source_xml, run_cfg, abort_event)

    monkeypatch.setattr(orch, "_push_target", flaky_push_target)

    summary = asyncio.run(orch.push(cfg))

    by_host = {r.host: r for r in summary.results}
    assert len(by_host) == 2
    assert by_host[HOST_OK].ok is True
    assert by_host["203.0.113.14"].ok is False
    assert "unexpected failure" in by_host["203.0.113.14"].error.lower()
