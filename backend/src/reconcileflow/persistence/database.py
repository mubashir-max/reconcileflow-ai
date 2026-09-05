"""Lazy SQLAlchemy engine and request-session lifecycle."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from reconcileflow.api.config import APISettings


class Database:
    """Own an engine and session factory without connecting during import or setup."""

    def __init__(self, settings: APISettings) -> None:
        self._settings = settings
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def is_initialized(self) -> bool:
        return self._engine is not None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            database_url = self._settings.database_url.get_secret_value()
            url = make_url(database_url)
            options: dict[str, object] = {
                "echo": self._settings.database_echo,
                "pool_pre_ping": True,
            }
            if url.get_backend_name() == "postgresql":
                options.update(
                    pool_size=self._settings.database_pool_size,
                    max_overflow=self._settings.database_max_overflow,
                    pool_timeout=self._settings.database_pool_timeout_seconds,
                )
            else:
                options["connect_args"] = {"check_same_thread": False}
            self._engine = create_engine(url, **options)
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                class_=Session,
                autoflush=False,
                expire_on_commit=False,
                close_resets_only=False,
            )
        return self._session_factory

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def check_connection(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
