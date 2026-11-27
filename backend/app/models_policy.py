# ───── Universal Engine + Per-Company Policy schema (Phase 1) ─────
# Per the spec: the audit MECHANISM is one shared codebase for every tenant;
# every number (a rate, a fixed-charge amount, an escrow target, a debt-recovery
# cap...) lives here, per tenant, never hardcoded. "company_*" in the spec ==
# "tenant" in this codebase — kept as tenant_id (String, FK -> tenants.id) to
# match the rest of the schema (models.py) rather than introducing a parallel
# "company" concept.
#
# driver_id / statement_id below are plain strings, NOT real foreign keys yet:
# drivers and statements currently live inside TenantData.payload (the JSON
# blob), not as their own tables. They reference the same ids the frontend
# already generates (e.g. "d_xxx", "ST-001"). Promoting drivers/statements to
# real relational tables is a later phase (Statement Parser Adapter / Universal
# Audit Engine), not part of this one.
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text, JSON, Date
from datetime import datetime
from app.database import Base


class CompanyDriverCategory(Base):
    """Rule 1/2/13: payment formula per driver category, versioned by effective date."""
    __tablename__ = "company_driver_categories"
    id                  = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id           = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    category_name       = Column(String, nullable=False)          # free text, e.g. "Company Driver", "Lease", "Owner-Operator"
    payment_method      = Column(String, nullable=False)          # per_mile | percentage | flat
    rate_value          = Column(Float, nullable=False)           # cents-per-mile, or percent (0-100), or flat cents
    effective_date_from = Column(Date, nullable=False)
    effective_date_to   = Column(Date, nullable=True)             # null = still in effect
    approved_by         = Column(Integer, ForeignKey("users.id"), nullable=True)
    note                = Column(Text, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)


class CompanyFixedCharge(Base):
    """Rule 3/7/9: recurring weekly charges, pro-rated on mid-period start/stop."""
    __tablename__ = "company_fixed_charges"
    id                  = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id           = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    charge_name         = Column(String, nullable=False)          # e.g. "Truck Lease", "Insurance", "IFTA", "Admin Fee"
    amount              = Column(Float, nullable=False)           # weekly amount, in cents
    applies_to_category = Column(String, nullable=True)           # matches CompanyDriverCategory.category_name, null = all
    proration_enabled   = Column(Boolean, default=True)
    effective_date_from = Column(Date, nullable=False)
    effective_date_to   = Column(Date, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)


class CompanyEscrowPolicy(Base):
    """Rule 8: escrow target + weekly deduction, one row per tenant."""
    __tablename__ = "company_escrow_policy"
    tenant_id              = Column(String, ForeignKey("tenants.id"), primary_key=True)
    target_amount          = Column(Float, nullable=False, default=0)   # cents
    weekly_deduction_amount = Column(Float, nullable=False, default=0)  # cents
    enabled                = Column(Boolean, default=False)
    updated_at             = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyDebtRecoveryPolicy(Base):
    """Rule 5: caps on how fast an advance/debt may be recovered from a single statement."""
    __tablename__ = "company_debt_recovery_policy"
    tenant_id                  = Column(String, ForeignKey("tenants.id"), primary_key=True)
    max_single_week_recovery_pct = Column(Float, nullable=False, default=100)  # % of gross or net, per tenant config
    min_net_pay_floor          = Column(Float, nullable=False, default=0)      # cents
    installment_required_above = Column(Float, nullable=True)                 # cents; null = no installment rule
    updated_at                 = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyMC(Base):
    """Rule 7: MC/unit list, grouped for reconciling a fixed charge split across several MC statements."""
    __tablename__ = "company_mc_list"
    id                  = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id           = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    mc_name             = Column(String, nullable=False)
    reconciliation_group = Column(String, nullable=True)   # charges across MCs with the same group get summed together
    created_at          = Column(DateTime, default=datetime.utcnow)


class CompanyDriverException(Base):
    """Rule 14: admin-approved exceptions to the standard category rate — never auto-flagged."""
    __tablename__ = "company_driver_exceptions"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id       = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    driver_id       = Column(String, nullable=False, index=True)   # id from the tenant's driver list (JSON blob)
    rate_value      = Column(Float, nullable=False)
    reason          = Column(Text, nullable=True)
    approved_by     = Column(Integer, ForeignKey("users.id"), nullable=True)
    effective_date  = Column(Date, nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)


class AuditAlert(Base):
    """Every rule violation — never auto-explained, only ever closed by a human response (Rule 12)."""
    __tablename__ = "audit_alerts"
    id                  = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id           = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    statement_id        = Column(String, nullable=False, index=True)
    driver_id           = Column(String, nullable=True, index=True)
    rule_code           = Column(String, nullable=False)        # e.g. "RULE_02_METHOD_MISMATCH"
    title               = Column(String, nullable=False)
    description         = Column(Text, nullable=True)
    expected_value      = Column(Float, nullable=True)
    actual_value        = Column(Float, nullable=True)
    severity            = Column(String, nullable=False, default="MEDIUM")   # CRITICAL | HIGH | MEDIUM | LOW
    status              = Column(String, nullable=False, default="OPEN")     # OPEN | EXPLAINED | RESOLVED
    accountant_response = Column(Text, nullable=True)
    resolved_by         = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    resolved_at         = Column(DateTime, nullable=True)


class StatementRawSection(Base):
    """Rule 4/11: a statement parsed into its own Earnings/Deductions/Other Pay/Balances sections —
    every audit check reads only from the section it concerns, never the whole raw statement text."""
    __tablename__ = "statement_raw_sections"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id       = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    statement_id    = Column(String, nullable=False, index=True)
    section_type    = Column(String, nullable=False)   # earnings | deductions | other_pay | balances
    raw_text        = Column(Text, nullable=True)
    structured_json = Column(JSON, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
