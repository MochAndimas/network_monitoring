"""Define module logic for `backend/app/services/audit_service.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import json

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.admin_audit_log import AdminAuditLog


async def record_admin_audit_log(
    db: AsyncSession,
    *,
    actor,
    action: str,
    target_type: str,
    target_id: str | None,
    ip_address: str = "",
    user_agent: str = "",
    details: dict | None = None,
    commit: bool = True,
) -> AdminAuditLog:
    """Persist an admin audit-log event for privileged actions.

    Args:
        db: Parameter input untuk routine ini.
        actor: Parameter input untuk routine ini.
        action: Parameter input untuk routine ini.
        target_type: Parameter input untuk routine ini.
        target_id: Parameter input untuk routine ini.
        ip_address: Parameter input untuk routine ini.
        user_agent: Parameter input untuk routine ini.
        details: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    user = getattr(actor, "user", None)
    entry = AdminAuditLog(
        actor_kind=str(getattr(actor, "kind", "unknown")),
        actor_id=getattr(user, "id", None),
        actor_username=getattr(user, "username", None),
        actor_role=str(getattr(actor, "role", "unknown")),
        actor_api_key_name=getattr(actor, "api_key_name", None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip_address=str(ip_address or ""),
        user_agent=str(user_agent or "")[:255],
        details_json=json.dumps(details or {}, ensure_ascii=True, default=str),
    )
    db.add(entry)
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(entry)
    return entry


async def list_admin_audit_logs(
    db: AsyncSession,
    *,
    limit: int = 100,
) -> list[AdminAuditLog]:
    """Return admin audit-log rows with optional filters and pagination.

    Args:
        db: Parameter input untuk routine ini.
        limit: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    rows = await db.scalars(select(AdminAuditLog).order_by(desc(AdminAuditLog.created_at), desc(AdminAuditLog.id)).limit(limit))
    return list(rows.all())
