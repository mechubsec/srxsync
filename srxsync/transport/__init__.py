"""Transport package: ABC + concrete backends + factory."""

from __future__ import annotations

from srxsync.transport.base import Transport, TransportError
from srxsync.transport.pyez import PyEZTransport

KNOWN_TRANSPORTS: tuple[str, ...] = ("pyez", "rustez")

__all__ = [
    "KNOWN_TRANSPORTS",
    "PyEZTransport",
    "Transport",
    "TransportError",
    "make_transport",
]


def make_transport(name: str) -> type[Transport]:
    """Resolve a transport name to a concrete Transport subclass.

    Raises:
        ValueError: name is not in KNOWN_TRANSPORTS.
        ImportError: the named backend is known but its optional
            dependency is not installed.
    """
    if name == "pyez":
        return PyEZTransport
    if name == "rustez":
        try:
            from srxsync.transport.rustez import RustezTransport
        except ImportError as e:
            raise ImportError(
                "rustez backend selected but 'rustez' is not installed "
                "-- run: pip install -e .[rust]"
            ) from e
        return RustezTransport
    raise ValueError(f"unknown transport {name!r}; known: {', '.join(KNOWN_TRANSPORTS)}")
