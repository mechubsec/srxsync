from __future__ import annotations

import os
from urllib.parse import urlparse

from srxsync.inventory import Auth
from srxsync.secrets.base import Secret, SecretError, SecretProvider

try:
    import hvac as _hvac
except ImportError:
    _hvac = None

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _require_secure_addr(addr: str) -> None:
    parsed = urlparse(addr)
    if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise SecretError(
            f"refusing plaintext VAULT_ADDR {addr!r}: http:// is only allowed "
            "to a loopback host — use https://"
        )


class VaultProvider(SecretProvider):
    def get(self, host: str, auth: Auth) -> Secret:
        if _hvac is None:
            raise SecretError("hvac not installed — pip install srxsync[vault]")
        if auth.path is None:
            raise SecretError("vault auth requires 'path'")
        addr = os.environ.get("VAULT_ADDR")
        token = os.environ.get("VAULT_TOKEN")
        if not addr or not token:
            raise SecretError("VAULT_ADDR and VAULT_TOKEN env vars required")
        _require_secure_addr(addr)
        client = _hvac.Client(url=addr, token=token)
        resp = client.secrets.kv.v2.read_secret_version(path=auth.path)
        data = resp["data"]["data"]
        if "username" not in data or "password" not in data:
            raise SecretError(f"vault secret at {auth.path} must contain username+password")
        return Secret(username=data["username"], password=data["password"])
