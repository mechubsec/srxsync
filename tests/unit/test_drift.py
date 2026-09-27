from pathlib import Path

from lxml import etree

from srxsync.drift import DriftDetector

FX = Path(__file__).parent.parent / "fixtures" / "configs"


def _load(name: str) -> etree._Element:
    return etree.parse(str(FX / name)).getroot()


def test_in_sync_when_identical():
    src = _load("source_minimal.xml")
    tgt = _load("source_minimal.xml")
    det = DriftDetector(paths=["/configuration/security"], prune=[])
    rep = det.diff(src, tgt)
    assert rep.in_sync is True
    assert rep.differing_paths == []


def test_detects_policy_difference():
    src = _load("source_minimal.xml")
    tgt = _load("target_drift.xml")
    det = DriftDetector(paths=["/configuration/security/policies"], prune=[])
    rep = det.diff(src, tgt)
    assert rep.in_sync is False
    assert "/configuration/security/policies" in rep.differing_paths


def test_drift_in_non_last_list_entry_is_detected():
    """Two <name-server> entries; only the first (non-last) one differs.

    A comparison that only looked at the last matching element (the M14 bug)
    would report this pair as in sync.
    """
    src = etree.fromstring(
        "<configuration><system>"
        "<name-server><name>8.8.8.8</name></name-server>"
        "<name-server><name>1.1.1.1</name></name-server>"
        "</system></configuration>"
    )
    tgt = etree.fromstring(
        "<configuration><system>"
        "<name-server><name>9.9.9.9</name></name-server>"
        "<name-server><name>1.1.1.1</name></name-server>"
        "</system></configuration>"
    )
    det = DriftDetector(paths=["/configuration/system/name-server"], prune=[])
    rep = det.diff(src, tgt)
    assert rep.in_sync is False
    assert "/configuration/system/name-server" in rep.differing_paths


def test_detects_system_category_drift_granularity():
    """Drift is reported per-category: ntp/time-zone/name-server drift but syslog
    and domain-name do not, proving category-level granularity."""
    src = _load("source_minimal.xml")
    tgt = _load("target_drift.xml")
    det = DriftDetector(
        paths=[
            "/configuration/system/name-server",
            "/configuration/system/ntp",
            "/configuration/system/syslog",
            "/configuration/system/domain-name",
            "/configuration/system/time-zone",
        ],
        prune=[],
    )
    rep = det.diff(src, tgt)
    assert rep.in_sync is False
    assert "/configuration/system/ntp" in rep.differing_paths
    assert "/configuration/system/time-zone" in rep.differing_paths
    assert "/configuration/system/name-server" in rep.differing_paths
    assert "/configuration/system/syslog" not in rep.differing_paths
    assert "/configuration/system/domain-name" not in rep.differing_paths
