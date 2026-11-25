"""Register the factors the platform can use, according to FACTOR_MODE.

mock (default): each owner's mock class, from app/factors/<name>/mock.py. A mock that
                does not exist yet is skipped, so the platform runs with whatever is ready
                (the fallback rule in CLAUDE.md §14).
real:           the real factors, added here as they are finished (weeks 4-11).
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


def register_factors(mode: str | None = None) -> list[str]:
    """Register every factor available in this mode; return their names. Safe to call twice."""
    mode = mode or factor_mode()
    if mode == "real":
        logger.warning("FACTOR_MODE=real: no real factors are implemented yet")
        return sorted(registered_factors())

    for name, (module_path, class_name) in MOCKS.items():
        if name in registered_factors():
            continue
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError as error:
            # Skip only if the mock file itself is missing; a broken import inside it is a real bug.
            if error.name not in (module_path, module_path.rsplit(".", 1)[0]):
                raise
            logger.warning("mock factor %s not found (%s), skipping", name, module_path)
            continue
        register(getattr(module, class_name)())
    return sorted(registered_factors())
