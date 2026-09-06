"""Local authentication primitives for ReconcileFlow."""

from .passwords import PasswordManager, normalize_email

__all__ = ["PasswordManager", "normalize_email"]
