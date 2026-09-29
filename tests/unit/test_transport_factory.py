"""Tests for srxsync.transport.make_transport factory."""

from __future__ import annotations

import sys

import pytest

from srxsync.transport import KNOWN_TRANSPORTS, make_transport
from srxsync.transport.pyez import PyEZTransport


def test_make_transport_pyez_returns_pyez_class() -> None:
    cls = make_transport("pyez")
    assert cls is PyEZTransport


def test_make_transport_unknown_raises_value_error_listing_known() -> None:
    with pytest.raises(ValueError) as exc_info:
        make_transport("nope")
    msg = str(exc_info.value)
    assert "nope" in msg
    for name in KNOWN_TRANSPORTS:
        assert name in msg


def test_known_transports_contains_both_backends() -> None:
    assert "pyez" in KNOWN_TRANSPORTS
    assert "rustez" in KNOWN_TRANSPORTS


def test_make_transport_rustez_missing_extra_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate rustez not being importable
    monkeypatch.setitem(sys.modules, "rustez", None)
    # Also evict the stub module so its `import rustez` re-runs
    monkeypatch.delitem(sys.modules, "srxsync.transport.rustez", raising=False)
    with pytest.raises(ImportError) as exc_info:
        make_transport("rustez")
    msg = str(exc_info.value)
    assert "rustez" in msg
    assert "pip install -e .[rust]" in msg
