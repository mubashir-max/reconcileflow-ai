"""FastAPI database dependencies."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .database import Database


def get_database(request: Request) -> Database:
    return request.app.state.database


DatabaseDependency = Annotated[Database, Depends(get_database)]


def get_db_session(database: DatabaseDependency) -> Iterator[Session]:
    with database.session() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_db_session)]
