"""Authenticated router-scoped bandwidth reporting."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...services.bandwidth_query_service import list_clients, query_usage
from ..schemas.bandwidth import ClientPage, UsagePage

router = APIRouter()
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("/{router_id}/clients", response_model=ClientPage)
async def clients(
    router_id: int,
    db: Database,
    limit: int = Query(50, ge=1, le=200),
    after_id: int = Query(0, ge=0),
) -> ClientPage:
    return await list_clients(db, router_id, limit, after_id)


@router.get("/{router_id}/usage/daily", response_model=UsagePage)
async def daily(
    router_id: int,
    db: Database,
    start: date,
    end: date,
    client_id: int | None = Query(None, ge=1),
) -> UsagePage:
    return await query_usage(db, router_id, start, end, client_id=client_id)


@router.get("/{router_id}/usage/top", response_model=UsagePage)
async def top(
    router_id: int,
    db: Database,
    start: date,
    end: date,
    client_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
) -> UsagePage:
    return await query_usage(db, router_id, start, end, top=True, client_id=client_id, limit=limit, offset=offset)
