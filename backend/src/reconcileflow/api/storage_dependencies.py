"""FastAPI dependencies for file storage."""

from typing import Annotated

from fastapi import Depends, Request

from reconcileflow.storage import FileStorage


def get_file_storage(request: Request) -> FileStorage:
    return request.app.state.file_storage


FileStorageDependency = Annotated[FileStorage, Depends(get_file_storage)]
