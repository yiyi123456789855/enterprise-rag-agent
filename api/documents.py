from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status

from api.dependencies import get_ingestion_service, get_repository, get_settings, get_vector_index
from app.schemas import DocumentResponse, JobResponse, UploadResponse


router = APIRouter(prefix="/api/v1", tags=["documents"])


@router.post("/documents", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    tenant_id: str = Form("default"),
    visibility: str = Form("public"),
    departments: str = Form("[]"),
) -> UploadResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds size limit")
    try:
        department_list = _parse_departments(departments)
        task = get_ingestion_service().enqueue(
            filename=file.filename or "document.txt",
            content=content,
            tenant_id=tenant_id,
            visibility=visibility,
            departments=department_list,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not task.duplicate:
        background_tasks.add_task(
            get_ingestion_service().process,
            task.job["id"],
            task.document["id"],
            file.filename or "document.txt",
            content,
        )
    return UploadResponse(
        document_id=task.document["id"],
        job_id=task.job["id"],
        status=task.job["status"],
        duplicate=task.duplicate,
    )


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(tenant_id: str = "default") -> list[dict]:
    return get_repository().list_documents(tenant_id)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> dict:
    try:
        return get_repository().get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, tenant_id: str = "default") -> None:
    try:
        document = get_repository().get_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    if document["tenant_id"] != tenant_id:
        raise HTTPException(status_code=404, detail="Document not found")
    vector_index = get_vector_index()
    if vector_index is not None:
        vector_index.delete_document(document_id)
    if not get_repository().delete_document(document_id, tenant_id):
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
