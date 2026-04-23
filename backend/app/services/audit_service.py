"""Provide business services that coordinate repositories and domain workflows for the network monitoring project."""

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
) -> AdminAuditLog:
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
    await db.commit()
    await db.refresh(entry)
    return entry


async def list_admin_audit_logs(
    db: AsyncSession,
    *,
    limit: int = 100,
) -> list[AdminAuditLog]:
    rows = await db.scalars(select(AdminAuditLog).order_by(desc(AdminAuditLog.created_at), desc(AdminAuditLog.id)).limit(limit))
    return list(rows.all())
