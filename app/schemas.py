from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import settings


DEFAULT_WHATSAPP_GROUP_NAME = "WhatsApp"
WHATSAPP_TIMEZONE = timezone(timedelta(hours=8))


_YINGDAO_TIMESTAMP_RE = re.compile(
    r"^\s*(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})\s*"
    r"(?P<period>上午|下午|AM|PM|am|pm)?\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*$"
)


def _normalize_yingdao_timestamp(value: str) -> str:
    match = _YINGDAO_TIMESTAMP_RE.match(value)
    if not match:
        return value

    hour = int(match.group("hour"))
    period = match.group("period")
    if period in {"下午", "PM", "pm"} and hour < 12:
        hour += 12
    elif period in {"上午", "AM", "am"} and hour == 12:
        hour = 0

    try:
        sent_at = datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            hour,
            int(match.group("minute")),
        )
    except ValueError:
        return value
    return sent_at.replace(tzinfo=WHATSAPP_TIMEZONE).isoformat(timespec="seconds")


class WhatsAppMessageIn(BaseModel):
    sender: str = Field(min_length=1)
    sent_at: str = Field(min_length=1, description="ISO string or WhatsApp timestamp text")
    text: str = ""
    external_message_id: str | None = None
    has_attachments: bool = False
    attachment_hints: list[dict[str, Any]] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_yingdao_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        aliases = {
            "sender": ("发送者", "發送者", "send_user", "sender_name"),
            "text": ("消息内容", "訊息內容", "message", "content"),
            "sent_at": ("时间", "時間", "send_time", "timestamp"),
        }
        for target, keys in aliases.items():
            if normalized.get(target):
                continue
            for key in keys:
                if normalized.get(key):
                    normalized[target] = normalized[key]
                    break

        if not normalized.get("raw_payload") and any(key in data for keys in aliases.values() for key in keys):
            normalized["raw_payload"] = data

        if isinstance(normalized.get("sent_at"), str):
            normalized["sent_at"] = _normalize_yingdao_timestamp(normalized["sent_at"])
        return normalized

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

    @model_validator(mode="before")
    @classmethod
    def normalize_yingdao_batch(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        if not normalized.get("messages"):
            for key in ("消息列表", "訊息列表", "message_list"):
                if normalized.get(key):
                    normalized["messages"] = normalized[key]
                    break

        if not normalized.get("group_name"):
            for key in ("群名称", "群名", "群組名稱", "groupName"):
                if normalized.get(key):
                    normalized["group_name"] = normalized[key]
                    break
        if not normalized.get("group_name") and settings.whatsapp_group_name:
            normalized["group_name"] = settings.whatsapp_group_name
        if not normalized.get("group_name"):
            normalized["group_name"] = DEFAULT_WHATSAPP_GROUP_NAME
        return normalized

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
