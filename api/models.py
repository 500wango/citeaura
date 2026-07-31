"""SaaS 数据模型。"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from api.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    plan = Column(String(32), nullable=False, default="trial", server_default="trial")
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    memberships = relationship("Membership", back_populates="tenant", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="tenant", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="tenant", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="tenant", cascade="all, delete-orphan")
    usage_counters = relationship("UsageCounter", back_populates="tenant", cascade="all, delete-orphan")
    invitations = relationship("TeamInvitation", back_populates="tenant", cascade="all, delete-orphan")
    platform_usage = relationship("PlatformUsage", back_populates="tenant", cascade="all, delete-orphan")
    sso_configuration = relationship(
        "SsoConfiguration", back_populates="tenant", cascade="all, delete-orphan", uselist=False,
    )
    audit_events = relationship("AuditEvent", back_populates="tenant", cascade="all, delete-orphan")
    integration_credentials = relationship(
        "IntegrationCredential", back_populates="tenant", cascade="all, delete-orphan",
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(320), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_memberships_role"),
    )

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(32), nullable=False, default="viewer", server_default="viewer")

    tenant = relationship("Tenant", back_populates="memberships")
    user = relationship("User", back_populates="memberships")


class TeamInvitation(Base):
    __tablename__ = "team_invitations"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_team_invitations_role"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(320), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tenant = relationship("Tenant", back_populates="invitations")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_projects_tenant_slug"),
        CheckConstraint(
            "schedule_interval_days IS NULL OR schedule_interval_days IN (7, 14, 30)",
            name="ck_projects_schedule_interval_days",
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    slug = Column(String(128), nullable=False)
    url = Column(String(2048), nullable=False)
    market = Column(String(16), nullable=False, default="both", server_default="both")
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    schedule_interval_days = Column(Integer, nullable=True)
    schedule_next_run_at = Column(DateTime(timezone=True), nullable=True, index=True)
    schedule_last_enqueued_at = Column(DateTime(timezone=True), nullable=True)
    platform_pool_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tenant = relationship("Tenant", back_populates="projects")
    jobs = relationship("Job", back_populates="project", cascade="all, delete-orphan")
    platform_usage = relationship("PlatformUsage", back_populates="project", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "engine_code", name="uq_api_keys_tenant_engine"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    engine_code = Column(String(64), nullable=False)
    encrypted_value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tenant = relationship("Tenant", back_populates="api_keys")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="queued", server_default="queued")
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    log_path = Column(String(2048), nullable=True)

    project = relationship("Project", back_populates="jobs")
    platform_usage = relationship("PlatformUsage", back_populates="job")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    plan = Column(String(32), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    tenant = relationship("Tenant", back_populates="subscriptions")


class UsageCounter(Base):
    __tablename__ = "usage_counters"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    month = Column(Date, primary_key=True)
    sample_runs = Column(Integer, nullable=False, default=0, server_default="0")
    projects_active = Column(Integer, nullable=False, default=0, server_default="0")
    platform_calls = Column(Integer, nullable=False, default=0, server_default="0")
    platform_cost_cny_fen = Column(Integer, nullable=False, default=0, server_default="0")

    tenant = relationship("Tenant", back_populates="usage_counters")


class PlatformUsage(Base):
    __tablename__ = "platform_usage"
    __table_args__ = (
        CheckConstraint("calls > 0", name="ck_platform_usage_calls_positive"),
        CheckConstraint("unit_price_cny_fen >= 0", name="ck_platform_usage_unit_price_nonnegative"),
        CheckConstraint("amount_cny_fen >= 0", name="ck_platform_usage_amount_nonnegative"),
        UniqueConstraint("job_id", "engine_code", name="uq_platform_usage_job_engine"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(64), nullable=False)
    engine_code = Column(String(64), nullable=False)
    calls = Column(Integer, nullable=False)
    unit_price_cny_fen = Column(Integer, nullable=False)
    amount_cny_fen = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    tenant = relationship("Tenant", back_populates="platform_usage")
    project = relationship("Project", back_populates="platform_usage")
    job = relationship("Job", back_populates="platform_usage")


class SsoConfiguration(Base):
    __tablename__ = "sso_configurations"
    __table_args__ = (
        CheckConstraint("default_role IN ('editor', 'viewer')", name="ck_sso_configurations_default_role"),
    )

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    provider_name = Column(String(128), nullable=False)
    issuer_url = Column(String(2048), nullable=False)
    client_id = Column(String(512), nullable=False)
    encrypted_client_secret = Column(Text, nullable=True)
    allowed_domains = Column(Text, nullable=False, default="[]", server_default="[]")
    default_role = Column(String(32), nullable=False, default="viewer", server_default="viewer")
    enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="sso_configuration")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(128), nullable=False, index=True)
    target = Column(String(2048), nullable=False)
    outcome = Column(String(32), nullable=False)
    ip_address = Column(String(64), nullable=True)
    details = Column(Text, nullable=False, default="{}", server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    tenant = relationship("Tenant", back_populates="audit_events")


class IntegrationCredential(Base):
    __tablename__ = "integration_credentials"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_integration_credentials_tenant_provider"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(64), nullable=False)
    encrypted_value = Column(Text, nullable=False)
    config_json = Column(Text, nullable=False, default="{}", server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="integration_credentials")
