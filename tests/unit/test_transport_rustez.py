"""RustezTransport error sanitization, without needing the rustez extra.

A fake ``rustez`` package is injected into sys.modules so the test runs on
any interpreter (CI uses 3.11; rustez only ships cp312 wheels).
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from typing import Any

import pytest
from lxml import etree

from srxsync.transport.base import TransportError

SECRET_TEXT = "policy allow-finance from zone trust user=admin tty=pts/0 src=10.9.9.9"


# Mirrors rustez.exceptions' real hierarchy (0.8.4 through 0.18.0).
class _RustEzError(Exception):
    pass


class _ConnectError(_RustEzError):
    pass


class _RpcError(_RustEzError):
    pass


class _RpcTimeoutError(_RpcError):
    pass


class _RustezTransportError(_RustEzError):
    pass


class _SessionExpiredError(_RustezTransportError):
    pass


def _raise(exc: Exception) -> Any:
    def _fn(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return _fn


@pytest.fixture
def rustez_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[types.ModuleType]:
    pkg = types.ModuleType("rustez")
    exc_mod = types.ModuleType("rustez.exceptions")
    for name, cls in {
        "RustEzError": _RustEzError,
        "ConnectError": _ConnectError,
        "ConnectAuthError": _ConnectError,
        "ConnectTimeoutError": _ConnectError,
        "ConfigLoadError": _RustEzError,
        "RpcError": _RpcError,
        "RpcTimeoutError": _RpcTimeoutError,
        "TransportError": _RustezTransportError,
        "SessionExpiredError": _SessionExpiredError,
    }.items():
        setattr(exc_mod, name, cls)
    pkg.Device = object  # type: ignore[attr-defined]
    pkg.Config = object  # type: ignore[attr-defined]
    pkg.exceptions = exc_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rustez", pkg)
    monkeypatch.setitem(sys.modules, "rustez.exceptions", exc_mod)
    monkeypatch.delitem(sys.modules, "srxsync.transport.rustez", raising=False)
    import srxsync.transport.rustez as mod

    yield mod
    monkeypatch.delitem(sys.modules, "srxsync.transport.rustez", raising=False)


def test_connect_error_text_is_not_leaked(
    rustez_module: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rustez_module, "Device", _raise(_SessionExpiredError(SECRET_TEXT)))
    tx = rustez_module.RustezTransport()
    with pytest.raises(TransportError) as info:
        tx.connect("192.0.2.1", "u", "p")
    assert SECRET_TEXT not in str(info.value)
    assert "_SessionExpiredError" in str(info.value)


def test_unlisted_subclass_during_commit_is_wrapped(rustez_module: types.ModuleType) -> None:
    """RpcTimeoutError-style subclasses must become TransportError, not escape raw."""
    tx = rustez_module.RustezTransport()
    cfg = types.SimpleNamespace(commit=_raise(_RpcTimeoutError(SECRET_TEXT)))
    tx._cfg = cfg
    with pytest.raises(TransportError) as info:
        tx.commit_confirmed(5)
    assert SECRET_TEXT not in str(info.value)


def test_load_and_fetch_errors_are_sanitized(rustez_module: types.ModuleType) -> None:
    tx = rustez_module.RustezTransport()
    tx._dev = types.SimpleNamespace(
        rpc=types.SimpleNamespace(get_config=_raise(_RpcError(SECRET_TEXT)))
    )
    with pytest.raises(TransportError) as info:
        tx.fetch(["/configuration/system/ntp"])
    assert SECRET_TEXT not in str(info.value)

    tx._cfg = types.SimpleNamespace(lock=lambda: None, load=_raise(_RustEzError(SECRET_TEXT)))
    with pytest.raises(TransportError) as info:
        tx.load(etree.Element("configuration"), "merge")
    assert SECRET_TEXT not in str(info.value)
