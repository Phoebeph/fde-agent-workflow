from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class WhatsAppMessageIn(BaseModel):
    sender: str = Field(min_length=1)
    sent_at: str = Field(min_length=1, description="ISO string or WhatsApp timestamp text")
    text: str = ""
    external_message_id: str | None = None
    has_attachments: bool = False
    attachment_hints: list[dict[str, Any]] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sender", "sent_at")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped


class WhatsAppMessageBatchIn(BaseModel):
    group_name: str = Field(min_length=1)
    messages: list[WhatsAppMessageIn] = Field(min_length=1)

    @field_validator("group_name")
    @classmethod
    def strip_group(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("group_name cannot be blank")
        return stripped


class MockWhatsAppMessageIn(BaseModel):
    sender: str = Field(min_length=1)
    text: str = Field(min_length=1)
    sent_at: str | None = None
    group_name: str | None = None
    has_attachments: bool = False
    attachment_hints: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("sender", "text")
    @classmethod
    def strip_mock_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped


class AttachmentIn(BaseModel):
    message_fingerprint: str = Field(min_length=16)
    original_filename: str = Field(min_length=1)
    temp_path: str = Field(min_length=1)
    attachment_type: Literal["image", "pdf", "video", "document", "other"] = "other"
    staff_name: str | None = None
    site: str | None = None
    work_type: str | None = None
    work_date: str | None = None


class RuleImportIn(BaseModel):
    path: str = Field(min_length=1)


class ScheduleRowIn(BaseModel):
    work_date: str = Field(min_length=1)
    staff_name: str = Field(min_length=1)
    task_text: str = Field(min_length=1)
    shift: str | None = None
    site: str | None = None
    source_file: str | None = None
    ocr_confidence: float | None = None
    review_status: Literal["pending", "confirmed", "rejected"] = "pending"


class ScheduleImportIn(BaseModel):
    rows: list[ScheduleRowIn] = Field(min_length=1)


class AnalyzeRunIn(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    sync_feishu: bool = True


class ReminderResultIn(BaseModel):
    reminder_id: int = Field(ge=1)
    status: Literal["sent", "failed", "skipped"]
    result_payload: dict[str, Any] = Field(default_factory=dict)


class StaffConfigIn(BaseModel):
    id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1)
    whatsapp_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    roles: list[
        Literal[
            "dispatch_manager",
            "followup_manager",
            "technician",
            "issue_reporter",
            "viewer",
        ]
    ] = Field(default_factory=list)
    feishu_name: str | None = None
    mention_name: str | None = None
    is_active: bool = True
    notes: str = ""

    @field_validator("name")
    @classmethod
    def strip_staff_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank")
        return stripped

    @field_validator("aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


class StaffActiveIn(BaseModel):
    is_active: bool


class SystemPrinciplesIn(BaseModel):
    principles: dict[str, Any] = Field(default_factory=dict)


class IssueConvertIn(BaseModel):
    staff_name: str = Field(min_length=1)
    work_date: str = Field(min_length=10)
    task_text: str = Field(min_length=1)
    site: str | None = None
    shift: str | None = None
    note: str = ""

    @field_validator("staff_name", "work_date", "task_text")
    @classmethod
    def strip_issue_convert_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped


class IssueDecisionIn(BaseModel):
    note: str = ""
