"""FastAPI dependencies for file storage."""

from typing import Annotated

from fastapi import Depends, Request

from reconcileflow.storage import LocalFileStorage


def get_file_storage(request: Request) -> LocalFileStorage:
    return request.app.state.file_storage


FileStorageDependency = Annotated[LocalFileStorage, Depends(get_file_storage)]
