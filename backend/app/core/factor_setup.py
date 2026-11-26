"""Register the factors the platform can use, according to FACTOR_MODE.

mock (default): each owner's mock class, from app/factors/<name>/mock.py.
real:           the real factor where one exists (app/factors/<name>/factor.py), otherwise
                that factor's mock. So the platform can run with, e.g., the real password
                factor and mock face while the real face factor is still being built.

A factor whose file does not exist yet is skipped, so the platform runs with whatever is
ready (the fallback rule in CLAUDE.md §14).
"""

from __future__ import annotations

import importlib
import logging

from app.factors.base import factor_mode, register, registered_factors

logger = logging.getLogger(__name__)

MOCKS = {
    "password": ("app.factors.password.mock", "MockPassword"),
    "passkey": ("app.factors.passkey.mock", "MockPasskey"),
    "keystroke": ("app.factors.keystroke.mock", "MockKeystroke"),
    "face": ("app.factors.face.mock", "MockFace"),
    "phone_approval": ("app.factors.phone_approval.mock", "MockPhoneApproval"),
}

# Real factors, added as they are finished.
REAL = {
    "password": ("app.factors.password.factor", "PasswordFactor"),  # week 4 (M3)
}


def _load(module_path: str, class_name: str):
    """Import the class, or return None if its file does not exist yet."""
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as error:
        # Skip only if the file itself is missing; a broken import inside it is a real bug.
        if error.name not in (module_path, module_path.rsplit(".", 1)[0]):
            raise
        return None
    return getattr(module, class_name)


def register_factors(mode: str | None = None) -> list[str]:
    """Register every factor available in this mode; return their names. Safe to call twice."""
    mode = mode or factor_mode()
    for name, mock in MOCKS.items():
        if name in registered_factors():
            continue
        cls = None
        if mode == "real" and name in REAL:
            cls = _load(*REAL[name])
            if cls is None:
                logger.warning("real factor %s not found (%s), using its mock", name, REAL[name][0])
        if cls is None:
            cls = _load(*mock)
        if cls is None:
            logger.warning("factor %s not found (%s), skipping", name, mock[0])
            continue
        register(cls())
    return sorted(registered_factors())
