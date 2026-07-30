"""SaaS 数据模型。"""

from sqlalchemy import (
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


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(320), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(32), nullable=False, default="viewer", server_default="viewer")

    tenant = relationship("Tenant", back_populates="memberships")
    user = relationship("User", back_populates="memberships")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_projects_tenant_slug"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    slug = Column(String(128), nullable=False)
    url = Column(String(2048), nullable=False)
    market = Column(String(16), nullable=False, default="both", server_default="both")
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tenant = relationship("Tenant", back_populates="projects")
    jobs = relationship("Job", back_populates="project", cascade="all, delete-orphan")


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

    tenant = relationship("Tenant", back_populates="usage_counters")
