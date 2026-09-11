"""Secure source-file upload and metadata endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from reconcileflow.persistence import PersistenceUnitOfWork, SessionDependency, StorageQuotaExceededError
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
    DirectUploadFinalizationRequest,
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
            work.organizations.apply_storage_delta(tenant.organization_id, stored.size_bytes)
        return _response(record)
    except StorageQuotaExceededError as error:
        if stored is not None:
            storage.delete(stored.storage_key)
        raise APIError(status_code=413, code="STORAGE_QUOTA_EXCEEDED", message="The organization storage quota has been exceeded.") from error
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


@router.delete(
    "/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a pending reconciliation source file",
    description="Requires OWNER, ADMIN, or ANALYST. Missing and cross-organization files are handled identically.",
    responses={409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def delete_source_file(
    file_id: uuid.UUID,
    session: SessionDependency,
    storage: FileStorageDependency,
    tenant: ReconciliationOperatorDependency,
) -> None:
    with PersistenceUnitOfWork(session) as work:
        record = work.source_files.find(file_id, organization_id=tenant.organization_id)
        if record is None:
            return None
        run = work.runs.get(record.run_id, organization_id=tenant.organization_id, lock=True)
        job = work.background_jobs.get_for_run(record.run_id, organization_id=tenant.organization_id)
        if run.status != "PENDING" or (job is not None and job.status in {"QUEUED", "RUNNING", "CANCEL_REQUESTED"}):
            raise APIError(status_code=409, code="FILE_IN_USE", message="The file cannot be deleted after processing has started.")
        if record.storage_key:
            try:
                if not storage.belongs_to_namespace(record.storage_key, namespace=str(tenant.organization_id)):
                    raise APIError(status_code=404, code="FILE_NOT_FOUND", message="The requested file does not exist.")
                storage.delete(record.storage_key)
            except APIError:
                raise
            except StorageOperationError as error:
                raise APIError(status_code=503, code="STORAGE_UNAVAILABLE", message="Object storage is temporarily unavailable.") from error
        size_bytes = record.size_bytes
        work.source_files.remove(record)
        work.organizations.apply_storage_delta(tenant.organization_id, -size_bytes)
        work.security_audit_events.append(
            organization_id=tenant.organization_id,
            actor_user_id=tenant.user_id,
            event_type="SOURCE_FILE_DELETED",
            details={"file_id": str(file_id), "run_id": str(record.run_id), "source_type": record.source_type},
        )
    return None


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
            if payload.size_bytes > storage.max_size_bytes:
                raise APIError(status_code=413, code="FILE_TOO_LARGE", message="The uploaded file exceeds the allowed size.")
            organization = work.organizations.get(tenant.organization_id, lock=True)
            if organization.storage_quota_bytes is not None and organization.storage_used_bytes + payload.size_bytes > organization.storage_quota_bytes:
                raise APIError(status_code=413, code="STORAGE_QUOTA_EXCEEDED", message="The organization storage quota has been exceeded.")
            key, url, fields = storage.create_upload_url(
                namespace=str(tenant.organization_id), filename=payload.filename,
                content_type=payload.content_type,
                checksum_sha256=payload.checksum_sha256, expires_seconds=ttl,
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


@router.post(
    "/reconciliation-runs/{run_id}/files/finalize",
    response_model=SourceFileMetadataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Finalize a direct object-storage upload",
    description="Verifies tenant ownership, authoritative metadata, checksum, and file contents before persistence.",
    responses=ERROR_RESPONSES | {503: {"model": ErrorResponse}},
)
def finalize_direct_upload(
    run_id: uuid.UUID,
    payload: DirectUploadFinalizationRequest,
    session: SessionDependency,
    storage: FileStorageDependency,
    tenant: ReconciliationOperatorDependency,
) -> SourceFileMetadataResponse:
    owned_object = False
    try:
        with PersistenceUnitOfWork(session) as work:
            run = work.runs.get(run_id, organization_id=tenant.organization_id, lock=True)
            if run.status != "PENDING":
                raise APIError(status_code=409, code="RUN_NOT_PENDING", message="Files can only be finalized for a pending reconciliation run.")
            if not storage.belongs_to_namespace(payload.storage_key, namespace=str(tenant.organization_id)):
                raise APIError(status_code=404, code="FILE_NOT_FOUND", message="The requested file does not exist.")
            existing = work.source_files.find_by_storage_key(
                payload.storage_key, organization_id=tenant.organization_id
            )
            if existing is not None:
                if existing.run_id == run_id and existing.source_type == payload.source_type.value:
                    return _response(existing)
                raise APIError(status_code=409, code="FILE_ALREADY_FINALIZED", message="The uploaded file has already been finalized.")
            owned_object = True
            metadata = storage.stat(payload.storage_key)
            if metadata.size_bytes != payload.size_bytes or metadata.size_bytes > storage.max_size_bytes:
                raise APIError(status_code=422, code="FILE_METADATA_MISMATCH", message="The uploaded file metadata could not be verified.")
            if metadata.content_type and metadata.content_type != payload.content_type:
                raise APIError(status_code=422, code="FILE_METADATA_MISMATCH", message="The uploaded file metadata could not be verified.")
            if metadata.checksum_sha256 and metadata.checksum_sha256 != payload.checksum_sha256:
                raise APIError(status_code=422, code="FILE_METADATA_MISMATCH", message="The uploaded file metadata could not be verified.")
            with storage.materialize(payload.storage_key) as path:
                inspected = storage.inspect_materialized(
                    path, original_filename=payload.original_filename,
                    storage_key=payload.storage_key,
                )
            if (
                inspected.size_bytes != payload.size_bytes
                or inspected.content_type != payload.content_type
                or inspected.checksum_sha256 != payload.checksum_sha256
            ):
                raise APIError(status_code=422, code="FILE_VALIDATION_FAILED", message="The uploaded file failed integrity validation.")
            record = work.source_files.add(
                run_id=run_id, source_type=payload.source_type.value,
                original_filename=inspected.original_filename,
                checksum_sha256=inspected.checksum_sha256,
                size_bytes=inspected.size_bytes, content_type=inspected.content_type,
                storage_key=payload.storage_key,
            )
            work.organizations.apply_storage_delta(tenant.organization_id, inspected.size_bytes)
            work.security_audit_events.append(
                organization_id=tenant.organization_id, actor_user_id=tenant.user_id,
                event_type="DIRECT_UPLOAD_FINALIZED",
                details={"run_id": str(run_id), "file_id": str(record.id), "source_type": record.source_type},
            )
        return _response(record)
    except StorageQuotaExceededError as error:
        if owned_object:
            storage.delete(payload.storage_key)
        raise APIError(status_code=413, code="STORAGE_QUOTA_EXCEEDED", message="The organization storage quota has been exceeded.") from error
    except APIError as error:
        if owned_object:
            storage.delete(payload.storage_key)
        raise
    except (EmptyUploadError, UploadTooLargeError, UnsupportedUploadError, InvalidStorageKeyError) as error:
        if owned_object:
            storage.delete(payload.storage_key)
        raise APIError(status_code=422, code="FILE_VALIDATION_FAILED", message="The uploaded file failed integrity validation.") from error
    except StorageNotFoundError as error:
        raise APIError(status_code=404, code="FILE_NOT_FOUND", message="The requested file does not exist.") from error
    except StorageOperationError as error:
        raise APIError(status_code=503, code="STORAGE_UNAVAILABLE", message="Object storage is temporarily unavailable.") from error
    except Exception:
        if owned_object:
            storage.delete(payload.storage_key)
        raise
