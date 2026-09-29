import pytest

from srxsync.inventory import Auth
from srxsync.secrets import Secret, SecretError, get_secret
from srxsync.secrets.env import EnvProvider
from srxsync.secrets.netrc_provider import NetrcProvider


def test_secret_dataclass():
    s = Secret(username="admin", password="hunter2")
    assert s.username == "admin"
    assert s.password == "hunter2"


def test_secret_repr_does_not_leak_password():
    s = Secret(username="admin", password="hunter2")
    assert "hunter2" not in repr(s)
    assert "admin" in repr(s)


def test_env_provider_reads_env(monkeypatch):
    monkeypatch.setenv("SRX_USER_SRX_A_EXAMPLE_NET", "admin")
    monkeypatch.setenv("SRX_PASSWORD_SRX_A_EXAMPLE_NET", "pw")
    secret = EnvProvider().get(host="srx-a.example.net", auth=Auth(provider="env"))
    assert secret.username == "admin"
    assert secret.password == "pw"


def test_env_provider_missing_raises(monkeypatch):
    monkeypatch.delenv("SRX_USER_SRX_A_EXAMPLE_NET", raising=False)
    with pytest.raises(SecretError, match="env var"):
        EnvProvider().get(host="srx-a.example.net", auth=Auth(provider="env"))


def test_env_provider_ssh_key(monkeypatch):
    monkeypatch.setenv("SRX_USER_SRX_A_EXAMPLE_NET", "admin")
    monkeypatch.delenv("SRX_PASSWORD_SRX_A_EXAMPLE_NET", raising=False)
    monkeypatch.setenv("SRX_SSH_KEY_SRX_A_EXAMPLE_NET", "~/.ssh/id_ed25519")
    secret = EnvProvider().get(host="srx-a.example.net", auth=Auth(provider="env"))
    assert secret.ssh_key_path is not None
    assert secret.ssh_key_path.endswith("id_ed25519")
    assert secret.password is None


def test_env_provider_needs_pw_or_key(monkeypatch):
    monkeypatch.setenv("SRX_USER_SRX_A_EXAMPLE_NET", "admin")
    monkeypatch.delenv("SRX_PASSWORD_SRX_A_EXAMPLE_NET", raising=False)
    monkeypatch.delenv("SRX_SSH_KEY_SRX_A_EXAMPLE_NET", raising=False)
    with pytest.raises(SecretError, match="either"):
        EnvProvider().get(host="srx-a.example.net", auth=Auth(provider="env"))


def test_netrc_provider(tmp_path, monkeypatch):
    netrc_file = tmp_path / ".netrc"
    netrc_file.write_text("machine srx-a.example.net login admin password hunter2\n")
    netrc_file.chmod(0o600)
    monkeypatch.setenv("HOME", str(tmp_path))
    secret = NetrcProvider().get(host="srx-a.example.net", auth=Auth(provider="netrc"))
    assert secret.username == "admin"
    assert secret.password == "hunter2"


def test_get_secret_dispatches_to_provider(monkeypatch):
    monkeypatch.setenv("SRX_USER_SRX_A_EXAMPLE_NET", "u")
    monkeypatch.setenv("SRX_PASSWORD_SRX_A_EXAMPLE_NET", "p")
    s = get_secret(host="srx-a.example.net", auth=Auth(provider="env"))
    assert s.username == "u"


def test_get_secret_unknown_provider_raises():
    with pytest.raises(SecretError, match="unknown provider"):
        get_secret(host="x", auth=Auth(provider="wizard"))
