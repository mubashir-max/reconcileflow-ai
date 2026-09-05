import pytest
from sqlalchemy import text
from sqlalchemy.exc import InvalidRequestError

from reconcileflow.api import APISettings
from reconcileflow.persistence import Base, Database


def _database():
    return Database(APISettings(database_url="sqlite+pysqlite:///:memory:", _env_file=None))


def test_declarative_base_is_available_for_future_models():
    assert Base.metadata is not None


def test_database_is_lazy_until_first_operation():
    database = _database()
    assert database.is_initialized is False
    _ = database.engine
    assert database.is_initialized is True


def test_connectivity_check_executes_select_one():
    database = _database()
    database.check_connection()
    database.dispose()
    assert database.is_initialized is False


def test_session_is_closed_after_context_exits():
    database = _database()
    with database.session() as session:
        assert session.scalar(text("SELECT 1")) == 1
    with pytest.raises(InvalidRequestError, match="permanently closed"):
        session.scalar(text("SELECT 1"))


def test_session_rolls_back_and_closes_on_error():
    database = _database()
    try:
        with database.session() as session:
            raise RuntimeError("operation failed")
    except RuntimeError:
        pass
    with pytest.raises(InvalidRequestError):
        session.scalar(text("SELECT 1"))
