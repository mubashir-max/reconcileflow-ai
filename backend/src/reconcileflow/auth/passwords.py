"""Password hashing and identity normalization utilities."""

from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


def normalize_email(email: str) -> str:
    """Return the canonical email representation used for lookup and storage."""

    return email.strip().lower()


class PasswordManager:
    """Hash and verify passwords using pwdlib's recommended Argon2 settings."""

    def __init__(self, password_hash: PasswordHash | None = None) -> None:
        self._password_hash = password_hash or PasswordHash.recommended()
        # Used when an email is unknown so login still performs an expensive hash check.
        self._dummy_hash = self._password_hash.hash("reconcileflow-dummy-password")

    def hash(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._password_hash.verify(password, password_hash)
        except (UnknownHashError, ValueError):
            return False

    def verify_dummy(self, password: str) -> None:
        self.verify(password, self._dummy_hash)
