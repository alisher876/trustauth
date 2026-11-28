"""Password rules (password/DESIGN.md §2, following NIST SP 800-63B).

- at least 8 characters, at most 128 (the maximum bounds the hashing work per request)
- any characters allowed, no composition rules ("one capital, one digit", ...)
- no forced periodic change
- leaked passwords are blocked separately (leaked.py)
"""

MIN_LENGTH = 8
MAX_LENGTH = 128


def policy_problem(password: str) -> str | None:
    """Return a reason code ("too_short" / "too_long") if the password breaks the rules, else None."""
    if len(password) < MIN_LENGTH:
        return "too_short"
    if len(password) > MAX_LENGTH:
        return "too_long"
    return None
