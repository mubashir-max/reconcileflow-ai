from reconcileflow.auth import PasswordManager, normalize_email


def test_passwords_are_hashed_and_verified() -> None:
    passwords = PasswordManager()
    raw_password = "correct horse battery staple"

    password_hash = passwords.hash(raw_password)

    assert raw_password not in password_hash
    assert password_hash.startswith("$argon2")
    assert passwords.verify(raw_password, password_hash) is True
    assert passwords.verify("wrong password", password_hash) is False


def test_invalid_stored_hash_fails_safely() -> None:
    assert PasswordManager().verify("password", "not-a-valid-hash") is False


def test_email_normalization_is_deterministic() -> None:
    assert normalize_email("  Owner@Example.COM ") == "owner@example.com"
