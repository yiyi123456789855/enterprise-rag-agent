from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_repository
from api.security import METRICS_READ_ROLES, get_auth_context, require_roles
from api.traffic import limit_read
from app.auth import AuthContext
from app.schemas import AuditEventResponse, AuditVerificationResponse


router = APIRouter(prefix="/api/v1/audit-events", tags=["audit"])


@router.get("", response_model=list[AuditEventResponse], dependencies=[Depends(limit_read)])
def list_audit_events(
    tenant_id: str = "default",
    limit: int = Query(default=100, ge=1, le=500),
    auth: AuthContext = Depends(get_auth_context),
) -> list[dict]:
    require_roles(auth, *METRICS_READ_ROLES)
    effective_tenant_id = tenant_id if auth.legacy else auth.tenant_id
    return get_repository().list_audit_events(effective_tenant_id, limit=limit)


@router.get(
    "/verify",
    response_model=AuditVerificationResponse,
    dependencies=[Depends(limit_read)],
)
def verify_audit_events(
    tenant_id: str = "default",
    auth: AuthContext = Depends(get_auth_context),
) -> AuditVerificationResponse:
    require_roles(auth, *METRICS_READ_ROLES)
    effective_tenant_id = tenant_id if auth.legacy else auth.tenant_id
    result = get_repository().verify_audit_chain(effective_tenant_id)
    return AuditVerificationResponse(tenant_id=effective_tenant_id, **result)
