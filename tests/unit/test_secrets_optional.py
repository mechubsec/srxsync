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

    with pytest.raises(SecretError, match="refusing plaintext"):
        vp._require_secure_addr("http://vault.example.net:8200")


def test_vault_allows_http_to_loopback():
    import srxsync.secrets.vault as vp

    vp._require_secure_addr("http://127.0.0.1:8200")
    vp._require_secure_addr("http://localhost:8200")


def test_vault_allows_https_to_any_host():
    import srxsync.secrets.vault as vp

    vp._require_secure_addr("https://vault.example.net:8200")
