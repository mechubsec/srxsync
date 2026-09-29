import pytest

from srxsync.inventory import Auth
from srxsync.secrets import SecretError


def test_keyring_provider_missing_extra_gives_helpful_error(monkeypatch):
    import srxsync.secrets.keyring_provider as kp

    monkeypatch.setattr(kp, "_keyring", None)
    with pytest.raises(SecretError, match="pip install"):
        kp.KeyringProvider().get(host="x", auth=Auth(provider="keyring", key="x"))


def test_vault_provider_missing_extra_gives_helpful_error(monkeypatch):
    import srxsync.secrets.vault as vp

    monkeypatch.setattr(vp, "_hvac", None)
    with pytest.raises(SecretError, match="pip install"):
        vp.VaultProvider().get(host="x", auth=Auth(provider="vault", path="secret/x"))


def test_vault_refuses_plaintext_http_to_a_non_loopback_host():
    import srxsync.secrets.vault as vp

    with pytest.raises(SecretError, match="refusing VAULT_ADDR"):
        vp._require_secure_addr("http://vault.example.net:8200")


def test_vault_allows_http_to_loopback():
    import srxsync.secrets.vault as vp

    vp._require_secure_addr("http://127.0.0.1:8200")
    vp._require_secure_addr("http://localhost:8200")


def test_vault_allows_https_to_any_host():
    import srxsync.secrets.vault as vp

    vp._require_secure_addr("https://vault.example.net:8200")


def test_vault_refuses_a_non_loopback_host_with_no_recognized_scheme():
    """A bare host:port (urlparse reads the host as the 'scheme') or an
    unlisted scheme like tcp:// used to fall through the old check, which
    only rejected 'http'. The check must be an allowlist (https, or http to
    loopback), not a denylist of one scheme."""
    import srxsync.secrets.vault as vp

    with pytest.raises(SecretError, match="refusing VAULT_ADDR"):
        vp._require_secure_addr("vault.example.net:8200")
    with pytest.raises(SecretError, match="refusing VAULT_ADDR"):
        vp._require_secure_addr("tcp://vault.example.net:8200")
