from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from jnpr.junos.exception import LockError
from lxml import etree

from srxsync.transport.base import TransportError
from srxsync.transport.pyez import PyEZTransport, _reason

_RPC_ERROR_XML = """
<rpc-error>
  <error-severity>error</error-severity>
  <error-info>
    <bad-element>policy ALLOW-INTERNAL-10.0.0.5</bad-element>
  </error-info>
  <error-message>statement not found near 10.0.0.5/32</error-message>
</rpc-error>
"""

_LOCK_RPC_ERROR_XML = """
<rpc-error>
  <error-severity>error</error-severity>
  <error-message>configuration database locked by: alice terminal pts/0 \
(pid 4242) on host from 198.51.100.7</error-message>
</rpc-error>
"""


def test_reason_never_echoes_device_rpc_error_body():
    """RpcError.__str__ embeds the device's bad_element/message, which can
    contain live config fragments (policy names, addresses). _reason() is
    what feeds TargetResult/DriftLine.error — and that gets printed straight
    to stdout — so it must never carry that raw text."""
    from jnpr.junos.exception import RpcError

    rsp = etree.fromstring(_RPC_ERROR_XML)
    err = RpcError(rsp=rsp)
    assert "10.0.0.5" in str(err)  # sanity: the raw exception does carry it

    reason = _reason(err)
    assert "10.0.0.5" not in reason
    assert "ALLOW-INTERNAL" not in reason
    assert reason == "RpcError"


def test_connect_locks_before_any_read(monkeypatch):
    """The candidate lock must be held for the whole session, including a
    read-only `check` (connect + fetch, no load). If connect() returned
    before locking, a concurrent session could mutate the candidate between
    our connect() and our first read, and we'd never know."""
    calls: list[str] = []

    fake_device = MagicMock()
    fake_device.open.side_effect = lambda: calls.append("open")
    monkeypatch.setattr("srxsync.transport.pyez.Device", lambda **kw: fake_device)

    fake_config = MagicMock()
    fake_config.lock.side_effect = lambda: calls.append("lock")
    monkeypatch.setattr("srxsync.transport.pyez.Config", lambda dev, mode: fake_config)

    t = PyEZTransport()
    t.connect("198.51.100.1", "svc", password="FAKEPASS")

    assert calls == ["open", "lock"]
    fake_config.lock.assert_called_once()


def test_connect_never_echoes_device_lock_error_body(monkeypatch):
    """A LockError raised by Config.lock() during connect() is an RpcError,
    not a ConnectError. Before this fix, connect() only wrapped ConnectError,
    so the raw LockError — whose str() embeds the device's lock-holder
    message (username, terminal, source IP) — propagated unwrapped up to
    the orchestrator, which prints it straight to stdout."""
    rsp = etree.fromstring(_LOCK_RPC_ERROR_XML)
    lock_err = LockError(rsp)
    assert "alice" in str(lock_err)
    assert "198.51.100.7" in str(lock_err)

    fake_device = MagicMock()
    fake_device.open.return_value = None
    monkeypatch.setattr("srxsync.transport.pyez.Device", lambda **kw: fake_device)
    fake_config = MagicMock()
    fake_config.lock.side_effect = lock_err
    monkeypatch.setattr("srxsync.transport.pyez.Config", lambda dev, mode: fake_config)

    t = PyEZTransport()
    with pytest.raises(TransportError) as exc_info:
        t.connect("198.51.100.1", "svc", password="FAKEPASS")

    message = str(exc_info.value)
    assert "alice" not in message
    assert "198.51.100.7" not in message
    assert "LockError" in message
