"""Drift detection: compare source vs target over a scoped set of XPaths."""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from srxsync.diff import DiffBuilder


@dataclass(frozen=True)
class DriftReport:
    host: str = ""
    differing_paths: list[str] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not self.differing_paths


@dataclass(frozen=True)
class DriftDetector:
    paths: list[str]
    prune: list[str]

    def diff(self, source: etree._Element, target: etree._Element, host: str = "") -> DriftReport:
        builder = DiffBuilder(paths=self.paths, prune=self.prune)
        src_scoped = builder.build(source)
        tgt_scoped = builder.build(target)

        differing: list[str] = []
        for abs_path in self.paths:
            rel = abs_path.removeprefix("/configuration/")
            # A path can match several sibling list entries (e.g. multiple
            # <name-server> elements). Compare the full list in document
            # order — .find() would only ever look at one element and miss
            # drift in any entry that isn't it. Order matters for Junos list
            # categories (e.g. name-server resolution order), so this must
            # not be sorted: a reordered-but-identical-set list is drift.
            src_nodes = [_canonicalize(n) for n in src_scoped.findall(rel)]
            tgt_nodes = [_canonicalize(n) for n in tgt_scoped.findall(rel)]
            if src_nodes != tgt_nodes:
                differing.append(abs_path)
        return DriftReport(host=host, differing_paths=differing)


def _canonicalize(node: etree._Element) -> bytes:
    result = etree.tostring(node, method="c14n2")
    return bytes(result) if not isinstance(result, bytes) else result
