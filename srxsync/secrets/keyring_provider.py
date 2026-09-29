from __future__ import annotations

from types import ModuleType

from srxsync.inventory import Auth
from srxsync.secrets.base import Secret, SecretError, SecretProvider

_keyring: ModuleType | None
try:
    import keyring as _keyring  # type: ignore[no-redef]
except ImportError:
    _keyring = None


class KeyringProvider(SecretProvider):
    def get(self, host: str, auth: Auth) -> Secret:
        if _keyring is None:
            raise SecretError("keyring not installed — pip install srxsync[keyring]")
        key = auth.key or host
        password = _keyring.get_password("srxsync", key)
        if password is None:
            raise SecretError(f"no keyring entry for srxsync/{key}")
        if ":" in password:
            user, _, pw = password.partition(":")
            return Secret(username=user, password=pw)
        raise SecretError(f"keyring entry srxsync/{key} must be 'username:password' form")
