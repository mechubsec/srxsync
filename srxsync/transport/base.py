"""Abstract transport interface for pushing configuration to a Junos device."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from lxml import etree


class TransportError(Exception):
    """Raised when a transport operation fails."""


class Transport(ABC):
    @abstractmethod
    def connect(
        self,
        host: str,
        username: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 830,
    ) -> None: ...

    @abstractmethod
    def fetch(self, paths: list[str]) -> etree._Element: ...

    @abstractmethod
    def load(self, xml: etree._Element, mode: Literal["replace", "merge"]) -> None: ...

    @abstractmethod
    def commit_confirmed(self, minutes: int) -> None: ...

    @abstractmethod
    def confirm(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
