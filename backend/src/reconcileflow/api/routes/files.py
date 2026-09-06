"""Secure source-file upload and metadata endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

from reconcileflow.persistence import PersistenceUnitOfWork, SessionDependency
from reconcileflow.storage import EmptyUploadError, UnsupportedUploadError, UploadTooLargeError

from ..errors import APIError
from ..file_schemas import SourceFileListResponse, SourceFileMetadataResponse, SourceFileType
from ..schemas import ErrorResponse
from ..storage_dependencies import FileStorageDependency


router = APIRouter(tags=["source files"])
ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "The reconciliation run or file does not exist."},
    409: {"model": ErrorResponse, "description": "The upload conflicts with the run state or existing data."},
    413: {"model": ErrorResponse, "description": "The upload exceeds the configured size limit."},
    415: {"model": ErrorResponse, "description": "The uploaded format or contents are unsupported."},
    422: {"model": ErrorResponse, "description": "The upload request is invalid."},
}


def _response(record) -> SourceFileMetadataResponse:
    return SourceFileMetadataResponse(
        id=record.id,
        run_id=record.run_id,
        source_type=record.source_type,
        original_filename=record.original_filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        checksum_sha256=record.checksum_sha256,
        row_count=record.row_count,
        created_at=record.created_at,
    )


@router.post(
    "/reconciliation-runs/{run_id}/files",
    response_model=SourceFileMetadataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a reconciliation source file",
    responses=ERROR_RESPONSES,
)
async def upload_source_file(
    run_id: uuid.UUID,
    session: SessionDependency,
    storage: FileStorageDependency,
    source_type: Annotated[SourceFileType, Form()],
    file: Annotated[UploadFile, File()],
) -> SourceFileMetadataResponse:
    stored = None
    try:
        with PersistenceUnitOfWork(session) as work:
            run = work.runs.get(run_id, lock=True)
            if run.status != "PENDING":
                raise APIError(
                    status_code=409,
                    code="RUN_NOT_PENDING",
                    message="Files can only be uploaded to a pending reconciliation run.",
                )
            try:
                stored = await storage.save(file)
            except EmptyUploadError as error:
                raise APIError(status_code=422, code="EMPTY_FILE", message="The uploaded file is empty.") from error
            except UploadTooLargeError as error:
                raise APIError(status_code=413, code="FILE_TOO_LARGE", message="The uploaded file exceeds the allowed size.") from error
            except UnsupportedUploadError as error:
                raise APIError(status_code=415, code="UNSUPPORTED_FILE", message="Only valid UTF-8 CSV and XLSX files are supported.") from error
            record = work.source_files.add(
                run_id=run_id,
                source_type=source_type.value,
                original_filename=stored.original_filename,
                checksum_sha256=stored.checksum_sha256,
                size_bytes=stored.size_bytes,
                content_type=stored.content_type,
                storage_key=stored.storage_key,
            )
        return _response(record)
    except Exception:
        if stored is not None:
            storage.delete(stored.storage_key)
        raise


@router.get(
    "/reconciliation-runs/{run_id}/files",
    response_model=SourceFileListResponse,
    summary="List source files for a reconciliation run",
    responses={404: ERROR_RESPONSES[404], 422: ERROR_RESPONSES[422]},
)
def list_source_files(run_id: uuid.UUID, session: SessionDependency) -> SourceFileListResponse:
    work = PersistenceUnitOfWork(session)
    work.runs.get(run_id)
    records = work.source_files.list_for_run(run_id)
    return SourceFileListResponse(items=[_response(record) for record in records], total=len(records))


@router.get(
    "/files/{file_id}",
    response_model=SourceFileMetadataResponse,
    summary="Get uploaded source-file metadata",
    responses={404: ERROR_RESPONSES[404], 422: ERROR_RESPONSES[422]},
)
def get_source_file(file_id: uuid.UUID, session: SessionDependency) -> SourceFileMetadataResponse:
    return _response(PersistenceUnitOfWork(session).source_files.get(file_id))
