from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from app.database import get_db
from app import models, auth
import uuid

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Schemas ──────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    company_name: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

# ── Endpoints ────────────────────────────────────────────
@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new company (tenant) and admin user."""
    if db.query(models.User).filter(models.User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create tenant
    tenant = models.Tenant(id=f"t_{uuid.uuid4().hex[:10]}", name=req.company_name)
    db.add(tenant)
    db.flush()

    # Create admin user
    user = models.User(
        tenant_id=tenant.id,
        email=req.email,
        hashed_password=auth.hash_password(req.password),
        name=req.name,
        role="COMPANY_ADMIN",
    )
    db.add(user)

    # Empty tenant data
    tenant_data = models.TenantData(tenant_id=tenant.id, payload={
        "mcs": [], "drivers": [], "trucks": [], "statements": [],
        "uploads": [], "fleet": [], "balances": [], "auditRuns": [],
        "auditLog": [], "policy": None, "policyHistory": [],
        "users": [], "periods": []
    })
    db.add(tenant_data)
    db.commit()
    db.refresh(user)

    token = auth.create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user=_user_dict(user),
    )

@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Login with email + password."""
    user = db.query(models.User).filter(models.User.email == form.username).first()
    if not user or not auth.verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    token = auth.create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user=_user_dict(user),
    )

@router.get("/me")
def me(current_user: models.User = Depends(auth.get_current_user)):
    """Get current user info."""
    return _user_dict(current_user)

def _user_dict(user: models.User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "tenant_id": user.tenant_id,
    }
