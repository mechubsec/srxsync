"""Concrete Transport over PyEZ / NETCONF."""

from __future__ import annotations

import contextlib
from typing import Literal

from jnpr.junos import Device
from jnpr.junos.exception import (
    ConnectError,
    RpcError,
)
from jnpr.junos.utils.config import Config
from lxml import etree

from srxsync.transport.base import Transport, TransportError


class PyEZTransport(Transport):
    def __init__(self) -> None:
        self._dev: Device | None = None
        self._cfg: Config | None = None

    def connect(
        self,
        host: str,
        username: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 830,
    ) -> None:
        try:
            self._dev = Device(
                host=host,
                user=username,
                password=password,
                ssh_private_key_file=ssh_key,
                port=port,
                normalize=True,
            )
            self._dev.open()
            self._cfg = Config(self._dev, mode="exclusive")
            self._cfg.lock()
        except (ConnectError, RpcError) as e:
            raise TransportError(f"connect failed for {host}: {_reason(e)}") from e

    def fetch(self, paths: list[str]) -> etree._Element:
        if self._dev is None:
            raise TransportError("not connected")
        root = etree.Element("configuration")
        for p in paths:
            rel = p.removeprefix("/configuration/")
            filter_xml = _build_filter(rel)
            try:
                resp = self._dev.rpc.get_config(filter_xml=filter_xml)
            except RpcError as e:
                raise TransportError(f"fetch failed at {p}: {_reason(e)}") from e
            for child in resp:
                root.append(child)
        return root

    def load(self, xml: etree._Element, mode: Literal["replace", "merge"]) -> None:
        if self._cfg is None:
            raise TransportError("not connected")
        try:
            self._cfg.load(
                etree.tostring(xml).decode(), format="xml", action=mode, ignore_warning=True
            )
        except RpcError as e:
            raise TransportError(f"load failed: {_reason(e)}") from e

    def commit_confirmed(self, minutes: int) -> None:
        if self._cfg is None:
            raise TransportError("not connected")
        try:
            self._cfg.commit(confirm=minutes)
        except RpcError as e:
            raise TransportError(f"commit confirmed failed: {_reason(e)}") from e

    def confirm(self) -> None:
        if self._cfg is None:
            raise TransportError("not connected")
        try:
            self._cfg.commit()
        except RpcError as e:
            raise TransportError(f"confirm commit failed: {_reason(e)}") from e

    def rollback(self) -> None:
        if self._cfg is None:
            return
        with contextlib.suppress(RpcError):
            self._cfg.rollback()

    def close(self) -> None:
        if self._cfg is not None:
            with contextlib.suppress(RpcError):
                self._cfg.unlock()
            self._cfg = None
        if self._dev is not None:
            with contextlib.suppress(Exception):
                self._dev.close()
            self._dev = None


def _reason(exc: Exception) -> str:
    """A short, safe failure reason — never the raw rpc-error text.

    jnpr's RpcError.__str__ embeds the device's bad_element and message,
    which can echo back fragments of the customer's live configuration
    (policy/zone/address names). That must not end up in a TargetResult or
    DriftLine error string, since those are printed straight to stdout.
    """
    return exc.__class__.__name__


def _build_filter(rel_path: str) -> str:
    parts = rel_path.split("/")
    inner = ""
    for p in reversed(parts):
        inner = f"<{p}>{inner}</{p}>"
    return f"<configuration>{inner}</configuration>"
