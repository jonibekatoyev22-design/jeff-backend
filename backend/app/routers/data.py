from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app import models, auth

router = APIRouter(prefix="/api/data", tags=["data"])

@router.get("/")
def get_data(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """Get all tenant data for the current user."""
    record = db.query(models.TenantData).filter(
        models.TenantData.tenant_id == user.tenant_id
    ).first()
    if not record:
        return {}
    return record.payload

@router.put("/")
def save_data(
    payload: dict,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Save (replace) all tenant data."""
    record = db.query(models.TenantData).filter(
        models.TenantData.tenant_id == user.tenant_id
    ).first()
    if record:
        record.payload = payload
        record.updated_at = datetime.utcnow()
    else:
        record = models.TenantData(tenant_id=user.tenant_id, payload=payload)
        db.add(record)
    db.commit()
    return {"ok": True}

@router.patch("/")
def patch_data(
    patch: dict,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Merge patch into existing tenant data (top-level keys only)."""
    record = db.query(models.TenantData).filter(
        models.TenantData.tenant_id == user.tenant_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="No data found")
    merged = {**record.payload, **patch}
    record.payload = merged
    record.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}
