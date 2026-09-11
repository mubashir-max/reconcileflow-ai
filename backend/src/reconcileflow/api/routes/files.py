"""Secure source-file upload and metadata endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from reconcileflow.persistence import PersistenceUnitOfWork, SessionDependency
from reconcileflow.storage import (
    EmptyUploadError,
    InvalidStorageKeyError,
    PresigningNotSupportedError,
    StorageNotFoundError,
    StorageOperationError,
    UnsupportedUploadError,
    UploadTooLargeError,
)

from ..errors import APIError
from ..auth_dependencies import ReconciliationOperatorDependency, TenantContextDependency, get_tenant_context
from ..file_schemas import (
    PresignedDownloadResponse,
    PresignedUploadRequest,
    PresignedUploadResponse,
    SourceFileListResponse,
    SourceFileMetadataResponse,
    SourceFileType,
)
from ..schemas import ErrorResponse
from ..storage_dependencies import FileStorageDependency


router = APIRouter(
    tags=["source files"],
    dependencies=[Depends(get_tenant_context)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
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
    description="Requires the OWNER, ADMIN, or ANALYST organization role.",
    responses=ERROR_RESPONSES,
)
async def upload_source_file(
    run_id: uuid.UUID,
    session: SessionDependency,
    storage: FileStorageDependency,
    tenant: ReconciliationOperatorDependency,
    source_type: Annotated[SourceFileType, Form()],
    file: Annotated[UploadFile, File()],
) -> SourceFileMetadataResponse:
    stored = None
    try:
        with PersistenceUnitOfWork(session) as work:
            run = work.runs.get(run_id, organization_id=tenant.organization_id, lock=True)
            if run.status != "PENDING":
                raise APIError(
                    status_code=409,
                    code="RUN_NOT_PENDING",
                    message="Files can only be uploaded to a pending reconciliation run.",
                )
            try:
                stored = await storage.save(file, namespace=str(tenant.organization_id))
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
def list_source_files(run_id: uuid.UUID, session: SessionDependency, tenant: TenantContextDependency) -> SourceFileListResponse:
    work = PersistenceUnitOfWork(session)
    work.runs.get(run_id, organization_id=tenant.organization_id)
    records = work.source_files.list_for_run(run_id)
    return SourceFileListResponse(items=[_response(record) for record in records], total=len(records))


@router.get(
    "/files/{file_id}",
    response_model=SourceFileMetadataResponse,
    summary="Get uploaded source-file metadata",
    responses={404: ERROR_RESPONSES[404], 422: ERROR_RESPONSES[422]},
)
def get_source_file(file_id: uuid.UUID, session: SessionDependency, tenant: TenantContextDependency) -> SourceFileMetadataResponse:
    return _response(PersistenceUnitOfWork(session).source_files.get(file_id, organization_id=tenant.organization_id))


def _presigning_error(error: Exception) -> APIError:
    if isinstance(error, PresigningNotSupportedError):
        return APIError(status_code=409, code="DIRECT_STORAGE_UNAVAILABLE", message="Direct object access is unavailable for the configured storage provider.")
    if isinstance(error, (InvalidStorageKeyError, UnsupportedUploadError)):
        return APIError(status_code=422, code="INVALID_FILE", message="The requested file type is unsupported.")
    if isinstance(error, StorageNotFoundError):
        return APIError(status_code=404, code="FILE_NOT_FOUND", message="The requested file does not exist.")
    return APIError(status_code=503, code="STORAGE_UNAVAILABLE", message="Object storage is temporarily unavailable.")


@router.post(
    "/reconciliation-runs/{run_id}/files/presigned-upload",
    response_model=PresignedUploadResponse,
    summary="Create a direct private-storage upload request",
    description="Requires OWNER, ADMIN, or ANALYST. The URL is short-lived and tenant-scoped.",
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def create_presigned_upload(
    run_id: uuid.UUID,
    payload: PresignedUploadRequest,
    request: Request,
    session: SessionDependency,
    storage: FileStorageDependency,
    tenant: ReconciliationOperatorDependency,
) -> PresignedUploadResponse:
    ttl = request.app.state.settings.presigned_url_ttl_seconds
    try:
        with PersistenceUnitOfWork(session) as work:
            run = work.runs.get(run_id, organization_id=tenant.organization_id)
            if run.status != "PENDING":
                raise APIError(status_code=409, code="RUN_NOT_PENDING", message="Files can only be uploaded to a pending reconciliation run.")
            key, url, fields = storage.create_upload_url(
                namespace=str(tenant.organization_id), filename=payload.filename,
                content_type=payload.content_type, expires_seconds=ttl,
            )
            work.security_audit_events.append(
                organization_id=tenant.organization_id, actor_user_id=tenant.user_id,
                event_type="PRESIGNED_UPLOAD_ISSUED",
                details={"run_id": str(run_id), "storage_key": key, "expires_in_seconds": ttl},
            )
        return PresignedUploadResponse(storage_key=key, url=url, fields=fields, expires_in_seconds=ttl)
    except APIError:
        raise
    except (PresigningNotSupportedError, InvalidStorageKeyError, UnsupportedUploadError, StorageOperationError) as error:
        raise _presigning_error(error) from error


@router.post(
    "/files/{file_id}/presigned-download",
    response_model=PresignedDownloadResponse,
    summary="Create a direct private-storage download URL",
    description="Requires an active membership in the file's organization. The URL is short-lived.",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def create_presigned_download(
    file_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    storage: FileStorageDependency,
    tenant: TenantContextDependency,
) -> PresignedDownloadResponse:
    ttl = request.app.state.settings.presigned_url_ttl_seconds
    try:
        with PersistenceUnitOfWork(session) as work:
            record = work.source_files.get(file_id, organization_id=tenant.organization_id)
            url = storage.create_download_url(record.storage_key, expires_seconds=ttl)
            work.security_audit_events.append(
                organization_id=tenant.organization_id, actor_user_id=tenant.user_id,
                event_type="PRESIGNED_DOWNLOAD_ISSUED",
                details={"file_id": str(file_id), "expires_in_seconds": ttl},
            )
        return PresignedDownloadResponse(url=url, expires_in_seconds=ttl)
    except (PresigningNotSupportedError, StorageNotFoundError, StorageOperationError) as error:
        raise _presigning_error(error) from error
