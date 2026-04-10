from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...api.deps import require_internal_api_key
from ...api.schemas import ThresholdItem, ThresholdUpdate
from ...db.session import get_db
from ...services.threshold_service import list_threshold_rows, update_threshold_value

router = APIRouter()


@router.get("", response_model=list[ThresholdItem])
async def list_thresholds(db: Session = Depends(get_db)) -> list[ThresholdItem]:
    return [ThresholdItem(**row) for row in list_threshold_rows(db)]


@router.put("/{key}", response_model=ThresholdItem, dependencies=[Depends(require_internal_api_key)])
async def update_threshold(key: str, payload: ThresholdUpdate, db: Session = Depends(get_db)) -> ThresholdItem:
    return ThresholdItem(**update_threshold_value(db, key, payload.value))
