from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.config import settings
from app.database import get_db
from app import models, auth
import uuid

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Schemas ──────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: str
    password: str
    fullName: str
    companyName: str
    legalName: Optional[str] = None
    country: Optional[str] = "US"
    timezone: Optional[str] = "America/New_York"
    currency: Optional[str] = "USD"
    businessType: Optional[str] = "Trucking Carrier"

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[dict] = None
    tenant: Optional[dict] = None
    pending: bool = False

# ── Endpoints ────────────────────────────────────────────
@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new company (tenant) and its first admin user.

    The platform owner's email is auto-approved and logged straight in.
    Everyone else is created with status=PENDING and must be approved by the
    platform owner before they can log in (see /approve below).
    """
    email = req.email.strip().lower()
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    is_platform_owner = email == settings.PLATFORM_OWNER_EMAIL.strip().lower()

    tenant = models.Tenant(
        id=f"t_{uuid.uuid4().hex[:10]}",
        name=req.companyName,
        legal_name=req.legalName or req.companyName,
        country=req.country or "US",
        timezone=req.timezone or "America/New_York",
        currency=req.currency or "USD",
        business_type=req.businessType or "Trucking Carrier",
        is_platform=is_platform_owner,
    )
    db.add(tenant)
    db.flush()

    user = models.User(
        tenant_id=tenant.id,
        email=email,
        hashed_password=auth.hash_password(req.password),
        name=req.fullName,
        role="SUPER_ADMIN" if is_platform_owner else "COMPANY_ADMIN",
        status="APPROVED" if is_platform_owner else "PENDING",
    )
    if is_platform_owner:
        user.approved_at = datetime.utcnow()
    db.add(user)
    db.flush()

    tenant_data = models.TenantData(tenant_id=tenant.id, payload={
        "mcs": [], "drivers": [], "trucks": [], "statements": [],
        "uploads": [], "fleet": [], "balances": [], "auditRuns": [],
        "auditLog": [], "policy": None, "policyHistory": [],
        "users": [], "periods": []
    })
    db.add(tenant_data)

    if is_platform_owner:
        auth.log_audit(db, tenant.id, user.id, "SYSTEM", "Platform owner workspace created", {"tenant": req.companyName})
    else:
        auth.log_audit(db, tenant.id, user.id, "SYSTEM", "Tenant pending approval", {"tenant": req.companyName, "email": email})

    db.commit()
    db.refresh(user)

    if not is_platform_owner:
        # No token: the account must wait for the platform owner to approve it.
        return TokenResponse(pending=True)

    token = auth.create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token, user=_user_dict(user), tenant=_tenant_dict(tenant))

@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Login with email + password (JSON body, matches the frontend's fetch call)."""
    email = req.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not auth.verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if user.status == "PENDING":
        raise HTTPException(status_code=403, detail="Your account is pending platform-owner approval. Please wait for approval.")
    if user.status == "REJECTED":
        raise HTTPException(status_code=403, detail="Your registration was rejected. Contact the platform owner.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    auth.log_audit(db, user.tenant_id, user.id, "AUTH", "User logged in", {"email": email})
    db.commit()

    token = auth.create_access_token({"sub": str(user.id)})
    tenant = db.query(models.Tenant).filter(models.Tenant.id == user.tenant_id).first()
    return TokenResponse(access_token=token, user=_user_dict(user), tenant=_tenant_dict(tenant))

# Kept for API-doc compatibility / Swagger's "Authorize" button (OAuth2 form login).
@router.post("/login-form", response_model=TokenResponse, include_in_schema=False)
def login_form(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    return login(LoginRequest(email=form.username, password=form.password), db)

@router.get("/me")
def me(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """Get current user + tenant info."""
    tenant = db.query(models.Tenant).filter(models.Tenant.id == current_user.tenant_id).first()
    return {"user": _user_dict(current_user), "tenant": _tenant_dict(tenant)}

# ── Platform-owner approval endpoints ────────────────────
@router.get("/pending")
def list_pending(db: Session = Depends(get_db), _: models.User = Depends(auth.require_super_admin)):
    """List all tenants/users waiting for platform-owner approval."""
    users = db.query(models.User).filter(models.User.status == "PENDING").order_by(models.User.created_at).all()
    out = []
    for u in users:
        t = db.query(models.Tenant).filter(models.Tenant.id == u.tenant_id).first()
        out.append({**_user_dict(u), "tenant": _tenant_dict(t)})
    return out

@router.post("/approve/{user_id}")
def approve_user(user_id: int, db: Session = Depends(get_db), admin: models.User = Depends(auth.require_super_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.status = "APPROVED"
    user.approved_at = datetime.utcnow()
    user.approved_by = admin.id
    auth.log_audit(db, user.tenant_id, admin.id, "SYSTEM", "User approved by platform owner", {"email": user.email})
    db.commit()
    return {"ok": True}

@router.post("/reject/{user_id}")
def reject_user(user_id: int, db: Session = Depends(get_db), admin: models.User = Depends(auth.require_super_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.status = "REJECTED"
    auth.log_audit(db, user.tenant_id, admin.id, "SYSTEM", "User rejected by platform owner", {"email": user.email})
    db.commit()
    return {"ok": True}

# ── Company-admin: invite a teammate into their own tenant ───
class InviteRequest(BaseModel):
    email: str
    fullName: str
    temp_password: str
    role: Optional[str] = "USER"

@router.post("/invite")
def invite_user(req: InviteRequest, db: Session = Depends(get_db), admin: models.User = Depends(auth.require_admin)):
    """Company admin adds a teammate directly into their own tenant (no public self-registration)."""
    email = req.email.strip().lower()
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    if req.role not in ("USER", "COMPANY_ADMIN"):
        raise HTTPException(status_code=400, detail="Invalid role")

    user = models.User(
        tenant_id=admin.tenant_id,
        email=email,
        hashed_password=auth.hash_password(req.temp_password),
        name=req.fullName,
        role=req.role,
        status="APPROVED",   # already inside an approved tenant — no extra platform-owner gate
        approved_at=datetime.utcnow(),
        approved_by=admin.id,
    )
    db.add(user)
    auth.log_audit(db, admin.tenant_id, admin.id, "SYSTEM", "Teammate invited", {"email": email, "role": req.role})
    db.commit()
    db.refresh(user)
    return _user_dict(user)

@router.get("/team")
def list_team(db: Session = Depends(get_db), admin: models.User = Depends(auth.require_admin)):
    """List everyone in the current admin's own tenant."""
    users = db.query(models.User).filter(models.User.tenant_id == admin.tenant_id).order_by(models.User.created_at).all()
    return [_user_dict(u) for u in users]

# ── Platform-owner: cross-tenant overview ────────────────
@router.get("/all-tenants")
def list_all_tenants(db: Session = Depends(get_db), _: models.User = Depends(auth.require_super_admin)):
    """Every tenant on the platform, with its primary admin/user and data counts
    (counts only — tenant data itself stays isolated, per the isolation requirement)."""
    tenants = db.query(models.Tenant).order_by(models.Tenant.created_at).all()
    out = []
    for t in tenants:
        primary = (
            db.query(models.User)
            .filter(models.User.tenant_id == t.id, models.User.role != "VIEWER")
            .order_by(models.User.created_at)
            .first()
        )
        record = db.query(models.TenantData).filter(models.TenantData.tenant_id == t.id).first()
        payload = record.payload if record else {}
        out.append({
            **_tenant_dict(t),
            "primaryUser": _user_dict(primary) if primary else None,
            "driverCount": len(payload.get("drivers", []) or []),
            "statementCount": len(payload.get("statements", []) or []),
        })
    return out

@router.delete("/tenant/{tenant_id}")
def delete_tenant(tenant_id: str, db: Session = Depends(get_db), admin: models.User = Depends(auth.require_super_admin)):
    """Delete a tenant and everything in it (users, data). Cannot delete the platform's own tenant."""
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.is_platform:
        raise HTTPException(status_code=400, detail="Cannot delete the platform tenant")

    db.query(models.User).filter(models.User.tenant_id == tenant_id).delete()
    db.query(models.TenantData).filter(models.TenantData.tenant_id == tenant_id).delete()
    db.query(models.AuditLogEntry).filter(models.AuditLogEntry.tenant_id == tenant_id).delete()
    db.delete(tenant)
    auth.log_audit(db, admin.tenant_id, admin.id, "PLATFORM", f"Tenant deleted: {tenant.name}", {"tenantId": tenant_id})
    db.commit()
    return {"ok": True}

def _user_dict(user: models.User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "fullName": user.name,
        "role": user.role,
        "status": user.status,
        "tenantId": user.tenant_id,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
    }

def _tenant_dict(tenant: models.Tenant) -> dict:
    if not tenant:
        return None
    return {
        "id": tenant.id,
        "name": tenant.name,
        "legalName": tenant.legal_name,
        "country": tenant.country,
        "timezone": tenant.timezone,
        "currency": tenant.currency,
        "businessType": tenant.business_type,
        "isPlatform": tenant.is_platform,
        "createdAt": tenant.created_at.isoformat() if tenant.created_at else None,
    }
