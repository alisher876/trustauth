"""Leaked-password check with a LOCAL list (password/DESIGN.md §3, option A).

The list is the UK NCSC "100k most used passwords" (from Have I Been Pwned), published in the
SecLists project. It is a public dataset, git-ignored, downloaded to:
    datasets/leaked-passwords/top-100000.txt     (see password/README.md)

Nothing is sent to an outside service: the whole check happens in memory, with a Python set
(lookup time does not depend on the list size).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parents[4] / "datasets" / "leaked-passwords" / "top-100000.txt"


class LeakedPasswordList:
    def __init__(self, passwords: set[str]) -> None:
        self._passwords = passwords

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "LeakedPasswordList":
        """Load one password per line. A missing file gives an EMPTY list and a warning.

        Path: argument, else the LEAKED_PASSWORDS_PATH environment variable (set in
        docker-compose.yml), else datasets/leaked-passwords/top-100000.txt.
        """
        path = Path(path or os.getenv("LEAKED_PASSWORDS_PATH") or DEFAULT_PATH)
        if not path.exists():
            logger.warning("leaked-password list not found at %s: leaked check is OFF", path)
            return cls(set())
        with path.open(encoding="utf-8", errors="ignore") as file:
            passwords = {line.rstrip("\r\n") for line in file if line.strip()}
        logger.info("loaded %d leaked passwords from %s", len(passwords), path)
        return cls(passwords)

    @property
    def is_loaded(self) -> bool:
        return bool(self._passwords)

    def __len__(self) -> int:
        return len(self._passwords)

    def contains(self, password: str) -> bool:
        """Exact match, or a match after lower-casing ("Password" counts as leaked "password")."""
        return password in self._passwords or password.lower() in self._passwords
