from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class Tenant(Base):
    __tablename__ = "tenants"
    id            = Column(String, primary_key=True)          # e.g. "t_abc123"
    name          = Column(String, nullable=False)
    legal_name    = Column(String, nullable=True)
    country       = Column(String, default="US")
    timezone      = Column(String, default="America/New_York")
    currency      = Column(String, default="USD")
    business_type = Column(String, default="Trucking Carrier")
    is_platform   = Column(Boolean, default=False)   # true only for the platform-owner's own tenant
    plan          = Column(String, default="basic")
    created_at    = Column(DateTime, default=datetime.utcnow)
    users         = relationship("User", back_populates="tenant")
    data          = relationship("TenantData", back_populates="tenant", uselist=False)

class User(Base):
    __tablename__ = "users"
    id                = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id         = Column(String, ForeignKey("tenants.id"), nullable=False)
    email             = Column(String, unique=True, nullable=False, index=True)
    hashed_password   = Column(String, nullable=False)
    name              = Column(String, nullable=False)
    role              = Column(String, default="USER")        # SUPER_ADMIN | COMPANY_ADMIN | USER
    status            = Column(String, default="PENDING")     # PENDING | APPROVED | REJECTED
    email_verified    = Column(Boolean, default=True)         # no SMTP wired up yet — see note in auth.py
    is_active         = Column(Boolean, default=True)
    created_at        = Column(DateTime, default=datetime.utcnow)
    approved_at       = Column(DateTime, nullable=True)
    approved_by       = Column(Integer, nullable=True)
    tenant            = relationship("Tenant", back_populates="users")

class TenantData(Base):
    """Stores all app data as JSON per tenant (mirrors the old localStorage structure)."""
    __tablename__ = "tenant_data"
    tenant_id  = Column(String, ForeignKey("tenants.id"), primary_key=True)
    payload    = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tenant     = relationship("Tenant", back_populates="data")

class AuditLogEntry(Base):
    """Server-side audit trail — who changed what, independent of the per-tenant JSON blob."""
    __tablename__ = "audit_log"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id   = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
    category    = Column(String, nullable=False)   # e.g. AUTH, SYSTEM, DATA
    message     = Column(String, nullable=False)
    meta        = Column(JSON, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, index=True)
