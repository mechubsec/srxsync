from __future__ import annotations

from lxml import etree

from srxsync.transport.pyez import _reason

_RPC_ERROR_XML = """
<rpc-error>
  <error-severity>error</error-severity>
  <error-info>
    <bad-element>policy ALLOW-INTERNAL-10.0.0.5</bad-element>
  </error-info>
  <error-message>statement not found near 10.0.0.5/32</error-message>
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
