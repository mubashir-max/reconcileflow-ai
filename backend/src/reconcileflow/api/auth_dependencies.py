"""Authentication service dependencies."""

from typing import Annotated

from fastapi import Depends

from reconcileflow.auth import PasswordManager


_password_manager = PasswordManager()


def get_password_manager() -> PasswordManager:
    return _password_manager


PasswordManagerDependency = Annotated[PasswordManager, Depends(get_password_manager)]
