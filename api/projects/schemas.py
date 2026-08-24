"""项目 API 请求模型。"""

from datetime import date
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from api.adapters import preflight


class ProjectCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    name: str | None = Field(default=None, max_length=128)
    skip_llm: bool = False
    no_sample: bool = False
    audit_id: str | None = Field(default=None, min_length=16, max_length=64)
    market: str = Field(default="both", pattern="^(cn|global|both)$")

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("url is required")
        if "://" not in value:
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("url must be a valid http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("url must not contain credentials, query, or fragment")
        return value.rstrip("/")


class SampleRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=1000)
    platforms: list[str] | None = None
    repeat: int = Field(default=1, ge=1, le=10)
    question_ids: list[str] | None = Field(default=None, max_length=1000)


class ProjectPreflight(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    question_count: int = Field(default=30, ge=1, le=1000)
    platforms: list[str] | None = None
    market: str = Field(default="both", pattern="^(cn|global|both)$")

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str):
        return preflight.normalize_url(value)


class TicketUpdate(BaseModel):
    status: str | None = None
    owner: str | None = Field(default=None, min_length=1, max_length=128)
    due_date: str | None = None
    note: str = Field(default="", max_length=2000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str):
        if value is None:
            return value
        if value not in ("todo", "doing", "done", "blocked", "wontfix"):
            raise ValueError("invalid ticket status")
        return value

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value):
        if value in (None, ""):
            return value
        date.fromisoformat(value)
        return value


class TicketBulkUpdate(TicketUpdate):
    ticket_ids: list[str] = Field(min_length=1, max_length=100)


class OffsiteTicketCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    ask_text: str = Field(min_length=1, max_length=5000)
    influenced_questions: list[str] = Field(min_length=1, max_length=200)


class PipelineActionRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class ScheduleRequest(BaseModel):
    interval_days: int = 0
    alert_on_regression: bool | None = None

    @field_validator("interval_days")
    @classmethod
    def validate_interval_days(cls, value: int):
        if value not in (0, 1, 7, 14, 30):
            raise ValueError("interval_days must be 0, 1, 7, 14, or 30")
        return value


class DeliverySendRequest(BaseModel):
    recipient_email: str | None = None


class SamplingFundingRequest(BaseModel):
    platform_pool_enabled: bool


class SamplingBudgetRequest(BaseModel):
    monthly_budget_cny_fen: int | None = Field(default=None, ge=0, le=100_000_000)
    sample_call_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    pause_on_budget_exceeded: bool = True


class SampleEstimateRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=1000)
    platforms: list[str] | None = None
    repeat: int = Field(default=1, ge=1, le=10)
    question_ids: list[str] | None = Field(default=None, max_length=1000)
