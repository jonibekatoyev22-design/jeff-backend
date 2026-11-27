# ───── Per-Company Policy API (Phase 1 of the Universal Audit Engine spec) ─────
# Read: any authenticated user, scoped to their own tenant.
# Write (create/update/delete): COMPANY_ADMIN or SUPER_ADMIN only — these are
# exactly the numbers the spec says must never be hardcoded in the engine, so
# they live here, per tenant, editable only by the people who own the policy.
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, models_policy as mp, auth

router = APIRouter(prefix="/api/policy", tags=["policy"])


def _tenant_of(user: models.User) -> str:
    return user.tenant_id


# ───── Driver categories (Rule 1/2/13) ─────
class DriverCategoryIn(BaseModel):
    category_name: str
    payment_method: str   # per_mile | percentage | flat
    rate_value: float
    effective_date_from: date
    effective_date_to: date | None = None
    note: str | None = None

@router.get("/driver-categories")
def list_driver_categories(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    rows = db.query(mp.CompanyDriverCategory).filter(mp.CompanyDriverCategory.tenant_id == _tenant_of(user)).order_by(mp.CompanyDriverCategory.effective_date_from.desc()).all()
    return [_category_out(r) for r in rows]

@router.post("/driver-categories")
def create_driver_category(body: DriverCategoryIn, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    if body.payment_method not in ("per_mile", "percentage", "flat"):
        raise HTTPException(400, "payment_method must be per_mile, percentage, or flat")
    row = mp.CompanyDriverCategory(tenant_id=_tenant_of(user), approved_by=user.id, **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    auth.log_audit(db, _tenant_of(user), user.id, "POLICY", f"Added driver category '{body.category_name}' ({body.payment_method} {body.rate_value})")
    db.commit()
    return _category_out(row)

@router.put("/driver-categories/{row_id}")
def update_driver_category(row_id: int, body: DriverCategoryIn, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyDriverCategory).filter(mp.CompanyDriverCategory.id == row_id, mp.CompanyDriverCategory.tenant_id == _tenant_of(user)).first()
    if not row: raise HTTPException(404, "Not found")
    for k, v in body.model_dump().items(): setattr(row, k, v)
    db.commit()
    return _category_out(row)

@router.delete("/driver-categories/{row_id}")
def delete_driver_category(row_id: int, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyDriverCategory).filter(mp.CompanyDriverCategory.id == row_id, mp.CompanyDriverCategory.tenant_id == _tenant_of(user)).first()
    if not row: raise HTTPException(404, "Not found")
    db.delete(row); db.commit()
    return {"ok": True}

def _category_out(r):
    return {"id": r.id, "categoryName": r.category_name, "paymentMethod": r.payment_method, "rateValue": r.rate_value,
            "effectiveDateFrom": r.effective_date_from.isoformat() if r.effective_date_from else None,
            "effectiveDateTo": r.effective_date_to.isoformat() if r.effective_date_to else None,
            "approvedBy": r.approved_by, "note": r.note}


# ───── Fixed charges (Rule 3/7/9) ─────
class FixedChargeIn(BaseModel):
    charge_name: str
    amount: float
    applies_to_category: str | None = None
    proration_enabled: bool = True
    effective_date_from: date
    effective_date_to: date | None = None

@router.get("/fixed-charges")
def list_fixed_charges(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    rows = db.query(mp.CompanyFixedCharge).filter(mp.CompanyFixedCharge.tenant_id == _tenant_of(user)).order_by(mp.CompanyFixedCharge.effective_date_from.desc()).all()
    return [_charge_out(r) for r in rows]

@router.post("/fixed-charges")
def create_fixed_charge(body: FixedChargeIn, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = mp.CompanyFixedCharge(tenant_id=_tenant_of(user), **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    auth.log_audit(db, _tenant_of(user), user.id, "POLICY", f"Added fixed charge '{body.charge_name}' ({body.amount})")
    db.commit()
    return _charge_out(row)

@router.put("/fixed-charges/{row_id}")
def update_fixed_charge(row_id: int, body: FixedChargeIn, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyFixedCharge).filter(mp.CompanyFixedCharge.id == row_id, mp.CompanyFixedCharge.tenant_id == _tenant_of(user)).first()
    if not row: raise HTTPException(404, "Not found")
    for k, v in body.model_dump().items(): setattr(row, k, v)
    db.commit()
    return _charge_out(row)

@router.delete("/fixed-charges/{row_id}")
def delete_fixed_charge(row_id: int, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyFixedCharge).filter(mp.CompanyFixedCharge.id == row_id, mp.CompanyFixedCharge.tenant_id == _tenant_of(user)).first()
    if not row: raise HTTPException(404, "Not found")
    db.delete(row); db.commit()
    return {"ok": True}

def _charge_out(r):
    return {"id": r.id, "chargeName": r.charge_name, "amount": r.amount, "appliesToCategory": r.applies_to_category,
            "prorationEnabled": r.proration_enabled,
            "effectiveDateFrom": r.effective_date_from.isoformat() if r.effective_date_from else None,
            "effectiveDateTo": r.effective_date_to.isoformat() if r.effective_date_to else None}


# ───── Escrow policy (Rule 8) — one row per tenant ─────
class EscrowIn(BaseModel):
    target_amount: float
    weekly_deduction_amount: float
    enabled: bool = True

@router.get("/escrow")
def get_escrow(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyEscrowPolicy).filter(mp.CompanyEscrowPolicy.tenant_id == _tenant_of(user)).first()
    if not row: return {"targetAmount": 0, "weeklyDeductionAmount": 0, "enabled": False}
    return {"targetAmount": row.target_amount, "weeklyDeductionAmount": row.weekly_deduction_amount, "enabled": row.enabled}

@router.put("/escrow")
def set_escrow(body: EscrowIn, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyEscrowPolicy).filter(mp.CompanyEscrowPolicy.tenant_id == _tenant_of(user)).first()
    if not row:
        row = mp.CompanyEscrowPolicy(tenant_id=_tenant_of(user))
        db.add(row)
    row.target_amount = body.target_amount
    row.weekly_deduction_amount = body.weekly_deduction_amount
    row.enabled = body.enabled
    row.updated_at = datetime.utcnow()
    db.commit()
    auth.log_audit(db, _tenant_of(user), user.id, "POLICY", "Updated escrow policy")
    db.commit()
    return {"ok": True}


# ───── Debt recovery policy (Rule 5) — one row per tenant ─────
class DebtRecoveryIn(BaseModel):
    max_single_week_recovery_pct: float
    min_net_pay_floor: float
    installment_required_above: float | None = None

@router.get("/debt-recovery")
def get_debt_recovery(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyDebtRecoveryPolicy).filter(mp.CompanyDebtRecoveryPolicy.tenant_id == _tenant_of(user)).first()
    if not row: return {"maxSingleWeekRecoveryPct": 100, "minNetPayFloor": 0, "installmentRequiredAbove": None}
    return {"maxSingleWeekRecoveryPct": row.max_single_week_recovery_pct, "minNetPayFloor": row.min_net_pay_floor,
            "installmentRequiredAbove": row.installment_required_above}

@router.put("/debt-recovery")
def set_debt_recovery(body: DebtRecoveryIn, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyDebtRecoveryPolicy).filter(mp.CompanyDebtRecoveryPolicy.tenant_id == _tenant_of(user)).first()
    if not row:
        row = mp.CompanyDebtRecoveryPolicy(tenant_id=_tenant_of(user))
        db.add(row)
    row.max_single_week_recovery_pct = body.max_single_week_recovery_pct
    row.min_net_pay_floor = body.min_net_pay_floor
    row.installment_required_above = body.installment_required_above
    row.updated_at = datetime.utcnow()
    db.commit()
    auth.log_audit(db, _tenant_of(user), user.id, "POLICY", "Updated debt recovery policy")
    db.commit()
    return {"ok": True}


# ───── MC / reconciliation groups (Rule 7) ─────
class MCIn(BaseModel):
    mc_name: str
    reconciliation_group: str | None = None

@router.get("/mc-list")
def list_mcs(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    rows = db.query(mp.CompanyMC).filter(mp.CompanyMC.tenant_id == _tenant_of(user)).order_by(mp.CompanyMC.mc_name).all()
    return [{"id": r.id, "mcName": r.mc_name, "reconciliationGroup": r.reconciliation_group} for r in rows]

@router.post("/mc-list")
def create_mc(body: MCIn, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = mp.CompanyMC(tenant_id=_tenant_of(user), **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "mcName": row.mc_name, "reconciliationGroup": row.reconciliation_group}

@router.delete("/mc-list/{row_id}")
def delete_mc(row_id: int, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyMC).filter(mp.CompanyMC.id == row_id, mp.CompanyMC.tenant_id == _tenant_of(user)).first()
    if not row: raise HTTPException(404, "Not found")
    db.delete(row); db.commit()
    return {"ok": True}


# ───── Approved driver exceptions (Rule 14) ─────
class ExceptionIn(BaseModel):
    driver_id: str
    rate_value: float
    reason: str | None = None
    effective_date: date

@router.get("/exceptions")
def list_exceptions(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    rows = db.query(mp.CompanyDriverException).filter(mp.CompanyDriverException.tenant_id == _tenant_of(user)).order_by(mp.CompanyDriverException.effective_date.desc()).all()
    return [{"id": r.id, "driverId": r.driver_id, "rateValue": r.rate_value, "reason": r.reason,
             "approvedBy": r.approved_by, "effectiveDate": r.effective_date.isoformat() if r.effective_date else None} for r in rows]

@router.post("/exceptions")
def create_exception(body: ExceptionIn, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = mp.CompanyDriverException(tenant_id=_tenant_of(user), approved_by=user.id, **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    auth.log_audit(db, _tenant_of(user), user.id, "POLICY", f"Approved rate exception for driver {body.driver_id}")
    db.commit()
    return {"ok": True, "id": row.id}

@router.delete("/exceptions/{row_id}")
def delete_exception(row_id: int, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    row = db.query(mp.CompanyDriverException).filter(mp.CompanyDriverException.id == row_id, mp.CompanyDriverException.tenant_id == _tenant_of(user)).first()
    if not row: raise HTTPException(404, "Not found")
    db.delete(row); db.commit()
    return {"ok": True}


# ───── Audit alerts (Rule 12) — created later by the Universal Audit Engine (Phase 3);
# this is the human-review surface: list + resolve, never auto-close. ─────
class AlertResolveIn(BaseModel):
    status: str                  # EXPLAINED | RESOLVED
    accountant_response: str

@router.get("/alerts")
def list_alerts(status: str | None = None, user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    q = db.query(mp.AuditAlert).filter(mp.AuditAlert.tenant_id == _tenant_of(user))
    if status: q = q.filter(mp.AuditAlert.status == status.upper())
    rows = q.order_by(mp.AuditAlert.created_at.desc()).limit(500).all()
    return [_alert_out(r) for r in rows]

@router.patch("/alerts/{alert_id}")
def resolve_alert(alert_id: int, body: AlertResolveIn, user: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    if body.status not in ("EXPLAINED", "RESOLVED"):
        raise HTTPException(400, "status must be EXPLAINED or RESOLVED")
    row = db.query(mp.AuditAlert).filter(mp.AuditAlert.id == alert_id, mp.AuditAlert.tenant_id == _tenant_of(user)).first()
    if not row: raise HTTPException(404, "Not found")
    row.status = body.status
    row.accountant_response = body.accountant_response
    row.resolved_by = user.id
    row.resolved_at = datetime.utcnow()
    db.commit()
    auth.log_audit(db, _tenant_of(user), user.id, "AUDIT_ALERT", f"Alert #{alert_id} marked {body.status}")
    db.commit()
    return _alert_out(row)

def _alert_out(r):
    return {"id": r.id, "statementId": r.statement_id, "driverId": r.driver_id, "ruleCode": r.rule_code,
            "title": r.title, "description": r.description, "expectedValue": r.expected_value, "actualValue": r.actual_value,
            "severity": r.severity, "status": r.status, "accountantResponse": r.accountant_response,
            "resolvedBy": r.resolved_by, "createdAt": r.created_at.isoformat() if r.created_at else None,
            "resolvedAt": r.resolved_at.isoformat() if r.resolved_at else None}
