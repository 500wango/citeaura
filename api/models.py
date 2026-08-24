"""SaaS 数据模型。"""

import re

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import relationship

from api.db import Base


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_tenants_status"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    directory_slug = Column(String(48), nullable=False, unique=True)
    plan = Column(String(32), nullable=False, default="trial", server_default="trial")
    status = Column(String(32), nullable=False, default="active", server_default="active")
    acquisition_country_code = Column(String(2), nullable=True, index=True)
    country_source = Column(String(32), nullable=True)
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    memberships = relationship("Membership", back_populates="tenant", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="tenant", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="tenant", cascade="all, delete-orphan")
    custom_providers = relationship("CustomProvider", back_populates="tenant", cascade="all, delete-orphan")
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
    api_access_tokens = relationship(
        "ApiAccessToken", back_populates="tenant", cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs):
        if not kwargs.get("directory_slug"):
            name = str(kwargs.get("name") or "").strip().lower()
            name = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", name).strip("-")
            kwargs["directory_slug"] = name[:48] or "workspace"
        super().__init__(**kwargs)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        CheckConstraint("registration_kind IN ('self_service', 'invited', 'sso')", name="ck_users_registration_kind"),
    )

    id = Column(Integer, primary_key=True)
    email = Column(String(320), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="active", server_default="active")
    registration_kind = Column(String(32), nullable=False, default="self_service", server_default="self_service")
    signup_country_code = Column(String(2), nullable=True, index=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True, index=True)
    session_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan",
    )
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="password_reset_tokens")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    family_id = Column(String(36), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")


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
            "schedule_interval_days IS NULL OR schedule_interval_days IN (1, 7, 14, 30)",
            name="ck_projects_schedule_interval_days",
        ),
        CheckConstraint(
            "monthly_budget_cny_fen IS NULL OR monthly_budget_cny_fen >= 0",
            name="ck_projects_monthly_budget_nonnegative",
        ),
        CheckConstraint(
            "sample_call_limit IS NULL OR sample_call_limit > 0",
            name="ck_projects_sample_call_limit_positive",
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
    monthly_budget_cny_fen = Column(Integer, nullable=True)
    sample_call_limit = Column(Integer, nullable=True)
    pause_on_budget_exceeded = Column(Boolean, nullable=False, default=True, server_default="true")
    alert_on_regression = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tenant = relationship("Tenant", back_populates="projects")
    jobs = relationship("Job", back_populates="project", cascade="all, delete-orphan")
    platform_usage = relationship("PlatformUsage", back_populates="project", cascade="all, delete-orphan")
    delivery_shares = relationship("DeliveryShare", back_populates="project", cascade="all, delete-orphan")


class DeliveryShare(Base):
    __tablename__ = "delivery_shares"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    delivery_date = Column(String(10), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    recipient_email = Column(String(320), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    project = relationship("Project", back_populates="delivery_shares")


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "engine_code", name="uq_api_keys_tenant_engine"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    engine_code = Column(String(64), nullable=False)
    encrypted_value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tenant = relationship("Tenant", back_populates="api_keys")


class CustomProvider(Base):
    __tablename__ = "custom_providers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_custom_providers_tenant_code"),
        CheckConstraint("market IN ('cn', 'global', 'both')", name="ck_custom_providers_market"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    base_url = Column(String(2048), nullable=False)
    model_id = Column(String(255), nullable=False)
    market = Column(String(16), nullable=False, default="both", server_default="both")
    encrypted_api_key = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tenant = relationship("Tenant", back_populates="custom_providers")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_jobs_project_active",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_jobs_project_id_id", "project_id", "id"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="queued", server_default="queued")
    stage = Column(String(64), nullable=False, default="queued", server_default="queued")
    progress = Column(Integer, nullable=False, default=0, server_default="0")
    reserved_platform_calls = Column(Integer, nullable=False, default=0, server_default="0")
    reserved_platform_cost_cny_fen = Column(Integer, nullable=False, default=0, server_default="0")
    budget_reservation_status = Column(String(32), nullable=True, index=True)
    attempt = Column(Integer, nullable=False, default=1, server_default="1")
    request_json = Column(Text, nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    retry_of_job_id = Column(Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    log_path = Column(String(2048), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    project = relationship("Project", back_populates="jobs")
    platform_usage = relationship("PlatformUsage", back_populates="job")
    retry_of = relationship("Job", remote_side=[id], uselist=False)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("billing_interval IN ('monthly', 'annual')", name="ck_subscriptions_billing_interval"),
        CheckConstraint(
            "status IN ('active', 'trialing', 'past_due', 'canceled', 'unpaid', 'incomplete')",
            name="ck_subscriptions_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    plan = Column(String(32), nullable=False)
    billing_interval = Column(String(16), nullable=False, default="monthly", server_default="monthly")
    amount_cny_fen = Column(Integer, nullable=True)
    amount_usd_cents = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="active", server_default="active")
    cancel_at_period_end = Column(Boolean, nullable=False, default=False, server_default="false")
    provider = Column(String(32), nullable=True)
    provider_customer_id = Column(String(255), nullable=True, index=True)
    provider_subscription_id = Column(String(255), nullable=True, unique=True)
    provider_checkout_session_id = Column(String(255), nullable=True, unique=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="subscriptions")


class BillingEvent(Base):
    __tablename__ = "billing_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_billing_events_provider_event"),
    )

    id = Column(Integer, primary_key=True)
    provider = Column(String(32), nullable=False)
    event_id = Column(String(255), nullable=False)
    event_type = Column(String(128), nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    notification_key = Column(String(255), nullable=True, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_payment_transactions_provider_event"),
        CheckConstraint("status IN ('succeeded', 'failed', 'refunded')", name="ck_payment_transactions_status"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)
    provider = Column(String(32), nullable=False)
    provider_event_id = Column(String(255), nullable=False)
    provider_invoice_id = Column(String(255), nullable=True, index=True)
    status = Column(String(32), nullable=False)
    currency = Column(String(3), nullable=False)
    amount_usd_cents = Column(Integer, nullable=True)
    billing_country_code = Column(String(2), nullable=True, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductEvent(Base):
    __tablename__ = "product_events"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    anonymous_id = Column(String(64), nullable=True, index=True)
    name = Column(String(64), nullable=False, index=True)
    country_code = Column(String(2), nullable=True, index=True)
    properties = Column(Text, nullable=False, default="{}", server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class PublicAudit(Base):
    """匿名公开审计结果，短期保存用于注册后的工作区继承。"""

    __tablename__ = "public_audits"
    __table_args__ = (
        UniqueConstraint("audit_id", name="uq_public_audits_audit_id"),
    )

    id = Column(Integer, primary_key=True)
    audit_id = Column(String(64), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    anonymous_id = Column(String(64), nullable=True, index=True)
    result_json = Column(Text, nullable=False, default="{}", server_default="{}")
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class ApiAccessToken(Base):
    """用于公共只读 API 和 MCP 的可撤销租户令牌，仅保存摘要。"""

    __tablename__ = "api_access_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_api_access_tokens_token_hash"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    token_prefix = Column(String(16), nullable=False)
    token_hash = Column(String(64), nullable=False)
    scopes = Column(Text, nullable=False, default='["read"]', server_default='["read"]')
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    tenant = relationship("Tenant", back_populates="api_access_tokens")


class PlatformAdmin(Base):
    __tablename__ = "platform_admins"
    __table_args__ = (
        CheckConstraint("role IN ('support', 'ops', 'finance', 'superadmin')", name="ck_platform_admins_role"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_platform_admins_status"),
    )

    id = Column(Integer, primary_key=True)
    email = Column(String(320), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False, default="superadmin", server_default="superadmin")
    status = Column(String(32), nullable=False, default="active", server_default="active")
    session_version = Column(Integer, nullable=False, default=0, server_default="0")
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AdminAuditEvent(Base):
    __tablename__ = "admin_audit_events"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("platform_admins.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(128), nullable=False, index=True)
    target = Column(String(2048), nullable=False)
    outcome = Column(String(32), nullable=False)
    ip_address = Column(String(64), nullable=True)
    details = Column(Text, nullable=False, default="{}", server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


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


class PlatformUsageOutbox(Base):
    """平台代付计量的持久化补偿事件。"""

    __tablename__ = "platform_usage_outbox"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_platform_usage_outbox_event_key"),
        CheckConstraint("calls > 0", name="ck_platform_usage_outbox_calls_positive"),
        CheckConstraint("status IN ('pending', 'processed')", name="ck_platform_usage_outbox_status"),
    )

    id = Column(Integer, primary_key=True)
    event_key = Column(String(255), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(64), nullable=False)
    engine_code = Column(String(64), nullable=False)
    calls = Column(Integer, nullable=False)
    unit_price_cny_fen = Column(Integer, nullable=False)
    amount_cny_fen = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="pending", server_default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)


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
