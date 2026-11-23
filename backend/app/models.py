from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class Tenant(Base):
    __tablename__ = "tenants"
    id         = Column(String, primary_key=True)          # e.g. "t_abc123"
    name       = Column(String, nullable=False)
    plan       = Column(String, default="basic")
    created_at = Column(DateTime, default=datetime.utcnow)
    users      = relationship("User", back_populates="tenant")
    data       = relationship("TenantData", back_populates="tenant", uselist=False)

class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id     = Column(String, ForeignKey("tenants.id"), nullable=False)
    email         = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    name          = Column(String, nullable=False)
    role          = Column(String, default="USER")        # SUPER_ADMIN | COMPANY_ADMIN | USER
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    tenant        = relationship("Tenant", back_populates="users")

class TenantData(Base):
    """Stores all app data as JSON per tenant (mirrors localStorage structure)."""
    __tablename__ = "tenant_data"
    tenant_id  = Column(String, ForeignKey("tenants.id"), primary_key=True)
    payload    = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tenant     = relationship("Tenant", back_populates="data")
