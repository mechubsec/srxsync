from pathlib import Path

from lxml import etree

from srxsync.diff import DiffBuilder

FIXTURE = Path(__file__).parent.parent / "fixtures" / "configs" / "source_minimal.xml"


def _load() -> etree._Element:
    return etree.parse(str(FIXTURE)).getroot()


def test_single_path_extract():
    src = _load()
    builder = DiffBuilder(paths=["/configuration/security/policies"], prune=[])
    out = builder.build(src)
    assert out.tag == "configuration"
    assert out.find(".//policies") is not None
    assert out.find(".//address-book") is None


def test_prune_strips_interface_bindings():
    src = _load()
    builder = DiffBuilder(
        paths=["/configuration/security/zones"],
        prune=["security-zone/interfaces"],
    )
    out = builder.build(src)
    zones = out.find(".//zones")
    assert zones is not None
    assert zones.find(".//security-zone/interfaces") is None
    assert zones.find(".//security-zone/host-inbound-traffic") is not None


def test_multiple_paths_all_included():
    src = _load()
    builder = DiffBuilder(
        paths=[
            "/configuration/security/policies",
            "/configuration/security/nat",
        ],
        prune=[],
    )
    out = builder.build(src)
    assert out.find(".//policies") is not None
    assert out.find(".//nat") is not None


def test_merge_mode_does_not_annotate_replace():
    src = _load()
    builder = DiffBuilder(paths=["/configuration/security/policies"], prune=[])
    out = builder.build(src, mode="merge")
    policies = out.find(".//policies")
    assert policies is not None
    assert policies.get("replace") is None


def test_extract_name_servers():
    src = _load()
    builder = DiffBuilder(paths=["/configuration/system/name-server"], prune=[])
    out = builder.build(src)
    assert out.find(".//system/name-server") is not None
    assert out.find(".//ntp") is None
    assert out.find(".//policies") is None


def test_extract_ntp():
    src = _load()
    builder = DiffBuilder(paths=["/configuration/system/ntp"], prune=[])
    out = builder.build(src)
    assert out.find(".//system/ntp") is not None
    assert out.find(".//name-server") is None
    assert out.find(".//policies") is None


def test_extract_syslog():
    src = _load()
    builder = DiffBuilder(paths=["/configuration/system/syslog"], prune=[])
    out = builder.build(src)
    assert out.find(".//system/syslog") is not None
    assert out.find(".//ntp") is None


def test_extract_domain_name():
    src = _load()
    builder = DiffBuilder(paths=["/configuration/system/domain-name"], prune=[])
    out = builder.build(src)
    domain = out.find(".//system/domain-name")
    assert domain is not None
    assert domain.text == "example.net"
    assert out.find(".//time-zone") is None


def test_extract_time_zone():
    src = _load()
    builder = DiffBuilder(paths=["/configuration/system/time-zone"], prune=[])
    out = builder.build(src)
    tz = out.find(".//system/time-zone")
    assert tz is not None
    assert tz.text == "UTC"
    assert out.find(".//domain-name") is None


def test_replace_mode_annotates_category_roots():
    src = _load()
    builder = DiffBuilder(
        paths=[
            "/configuration/security/policies",
            "/configuration/security/nat",
        ],
        prune=[],
    )
    out = builder.build(src, mode="replace")
    assert out.find(".//policies").get("replace") == "replace"
    assert out.find(".//nat").get("replace") == "replace"
    # Non-category ancestors (<security>) are NOT annotated — would over-wipe
    assert out.find(".//security").get("replace") is None


def test_list_category_keeps_every_sibling_entry():
    """source_minimal.xml has two <name-server> siblings under <system>.

    Both must survive the graft — collapsing to only the last one is exactly
    the bug that let drift on an earlier list entry go unreported.
    """
    src = _load()
    builder = DiffBuilder(paths=["/configuration/system/name-server"], prune=[])
    out = builder.build(src)
    servers = out.findall(".//system/name-server")
    assert len(servers) == 2
    names = {s.findtext("name") for s in servers}
    assert names == {"8.8.8.8", "1.1.1.1"}
