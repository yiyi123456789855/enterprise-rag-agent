from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from api.dependencies import (
    get_ingestion_dispatcher,
    get_ingestion_service,
    get_repository,
    get_settings,
    get_upload_store,
    get_vector_index,
)
from api.security import ADMIN_ROLES, DOCUMENT_WRITE_ROLES, get_auth_context, require_roles
from api.traffic import limit_read, limit_upload
from app.auth import AuthContext
from app.auditing import audit_request
from app.schemas import DocumentResponse, JobResponse, UploadResponse
from ingestion.upload_store import UploadTooLargeError


router = APIRouter(prefix="/api/v1", tags=["documents"])


@router.post(
    "/documents",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_upload)],
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    tenant_id: str = Form("default"),
    visibility: str = Form("public"),
    departments: str = Form("[]"),
    auth: AuthContext = Depends(get_auth_context),
) -> UploadResponse:
    require_roles(auth, *DOCUMENT_WRITE_ROLES)
    upload_store = get_upload_store()
    try:
        content_path = await upload_store.save(
            file,
            get_settings().max_upload_mb * 1024 * 1024,
        )
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        department_list = _parse_departments(departments)
        effective_tenant_id = tenant_id if auth.legacy else auth.tenant_id
        if (
            not auth.legacy
            and visibility == "department"
            and not auth.has_any_role(*ADMIN_ROLES)
            and not set(department_list).issubset(auth.departments)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot assign a document to departments outside the authenticated scope",
            )
        task = get_ingestion_service().enqueue_file(
            filename=file.filename or "document.txt",
            content_path=content_path,
            tenant_id=effective_tenant_id,
            visibility=visibility,
            departments=department_list,
            audit=audit_request(request, auth, get_settings().audit_hmac_key),
        )
    except HTTPException:
        upload_store.delete(content_path)
        raise
    except ValueError as exc:
        upload_store.delete(content_path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        upload_store.delete(content_path)
        raise
    if task.duplicate:
        upload_store.delete(content_path)
    else:
        try:
            content_path = upload_store.promote(content_path, task.job["id"])
            get_ingestion_dispatcher().dispatch(
                job_id=task.job["id"],
                document_id=task.document["id"],
                filename=file.filename or "document.txt",
                content_path=str(content_path),
            )
        except (RuntimeError, ValueError) as exc:
            upload_store.delete(content_path)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    current_job = get_repository().get_job(task.job["id"])
    return UploadResponse(
        document_id=task.document["id"],
        job_id=task.job["id"],
        status=current_job["status"],
        duplicate=task.duplicate,
    )


@router.get(
    "/documents",
    response_model=list[DocumentResponse],
    dependencies=[Depends(limit_read)],
)
def list_documents(
    tenant_id: str = "default",
    auth: AuthContext = Depends(get_auth_context),
) -> list[dict]:
    if auth.legacy:
        return get_repository().list_documents(tenant_id)
    departments = None if auth.has_any_role(*ADMIN_ROLES) else list(auth.departments)
    return get_repository().list_documents(auth.tenant_id, departments=departments)


@router.get(
    "/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(limit_read)]
)
def get_job(job_id: str, auth: AuthContext = Depends(get_auth_context)) -> dict:
    try:
        if auth.legacy:
            return get_repository().get_job(job_id)
        departments = None if auth.has_any_role(*ADMIN_ROLES) else list(auth.departments)
        return get_repository().get_job_for_tenant(job_id, auth.tenant_id, departments)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_upload)],
)
def delete_document(
    request: Request,
    document_id: str,
    tenant_id: str = "default",
    auth: AuthContext = Depends(get_auth_context),
) -> None:
    require_roles(auth, *ADMIN_ROLES)
    effective_tenant_id = tenant_id if auth.legacy else auth.tenant_id
    try:
        document = get_repository().get_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    if document["tenant_id"] != effective_tenant_id:
        raise HTTPException(status_code=404, detail="Document not found")
    vector_index = get_vector_index()
    if vector_index is not None:
        vector_index.delete_document(document_id)
    if not get_repository().delete_document(
        document_id,
        effective_tenant_id,
        audit=audit_request(request, auth, get_settings().audit_hmac_key),
    ):
        raise HTTPException(status_code=404, detail="Document not found")


def _parse_departments(raw: str) -> list[str]:
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        value = json.loads(stripped)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("departments must be a JSON string array")
        return value
    return [item.strip() for item in stripped.split(",") if item.strip()]
