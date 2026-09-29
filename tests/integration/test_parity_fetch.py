"""PyEZ vs rustez fetch parity — canonical-XML equality.

Skips if tests/lab.yaml is absent or if rustez is not installed.
"""

from __future__ import annotations

import difflib
import importlib.util
from typing import TypedDict

import pytest
from lxml import etree

from srxsync.categories import CategoryModel
from srxsync.inventory import Auth, load_inventory
from srxsync.secrets import get_secret
from srxsync.transport import PyEZTransport, Transport
from tests.integration.conftest import LAB_FILE

pytestmark = pytest.mark.integration


class _ParityCtx(TypedDict):
    host: str
    paths: list[str]


def _rustez_available() -> bool:
    return importlib.util.find_spec("rustez") is not None


@pytest.fixture(scope="module")
def parity_ctx(lab: None) -> _ParityCtx:
    if not _rustez_available():
        pytest.skip("rustez not installed - run: pip install -e .[rust]")
    cats = CategoryModel.default()
    inv = load_inventory(LAB_FILE, known_categories=cats.known_names())
    # Union of target-include category names, preserving order.
    union: list[str] = []
    seen: set[str] = set()
    for t in inv.targets:
        for name in t.include:
            if name not in seen:
                union.append(name)
                seen.add(name)
    paths, unknown = cats.resolve(union)
    assert not unknown, f"lab inventory references unknown categories: {unknown}"
    return {"host": inv.source.host, "paths": paths}


def _fetch(transport_cls: type[Transport], host: str, paths: list[str]) -> etree._Element:
    t = transport_cls()
    secret = get_secret(host=host, auth=Auth(provider="env"))
    t.connect(host, secret.username, secret.password, ssh_key=secret.ssh_key_path)
    try:
        return t.fetch(paths)
    finally:
        t.close()


_VOLATILE_ATTRS = {"changed-localtime", "changed-seconds"}


def _normalize(root: etree._Element) -> etree._Element:
    """Strip volatile NETCONF metadata attrs and insignificant whitespace text nodes.

    PyEZ (normalize=True) returns compact XML; rustez returns pretty-printed XML.
    c14n2 preserves whitespace-only text nodes, so we strip them from both sides
    to achieve a purely structural comparison.
    """
    for element in root.iter():
        for attr in _VOLATILE_ATTRS:
            element.attrib.pop(attr, None)
        if element.text and not element.text.strip():
            element.text = None
        if element.tail and not element.tail.strip():
            element.tail = None
    return root


def test_pyez_and_rustez_fetch_produces_same_canonical_xml(parity_ctx: _ParityCtx) -> None:
    from srxsync.transport.rustez import RustezTransport

    host = parity_ctx["host"]
    paths = parity_ctx["paths"]

    pyez_xml = _normalize(_fetch(PyEZTransport, host, paths))
    rustez_xml = _normalize(_fetch(RustezTransport, host, paths))

    pyez_canon = etree.tostring(pyez_xml, method="c14n2")
    rustez_canon = etree.tostring(rustez_xml, method="c14n2")

    if pyez_canon != rustez_canon:
        diff = "\n".join(
            difflib.unified_diff(
                pyez_canon.decode().splitlines(),
                rustez_canon.decode().splitlines(),
                lineterm="",
                fromfile="pyez",
                tofile="rustez",
                n=3,
            )
        )
        pytest.fail(f"fetch parity mismatch:\n{diff[:4000]}")
