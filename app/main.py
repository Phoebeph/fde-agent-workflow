from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import threading
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.admin_ui import admin_settings_html
from app.config import settings
from app.database import Database
from app.logging_config import configure_backend_logging
from app.schemas import (
    AnalyzeRunIn,
    AnalyzeResetIn,
    AutomationReportIn,
    AttachmentIn,
    IssueConvertIn,
    IssueDecisionIn,
    MockWhatsAppMessageIn,
    ReminderPreviewIn,
    ReminderResultIn,
    RuleImportIn,
    ScheduleImportIn,
    SiteActiveIn,
    SiteConfigIn,
    StaffActiveIn,
    StaffConfigIn,
    SystemPrinciplesIn,
    WhatsAppMessageBatchIn,
)
from app.services.archive import archive_attachment, safe_part
from app.services.automation import SCAN_CYCLE, STALE_CLAIM_SECONDS, build_due_automation_jobs, parse_site_names_csv
from app.services.completion import apply_schedule_completion, schedule_gap_analysis
from app.services.customer_config import CustomerSettings, CustomerSettingsStore
from app.services.diagnostics import build_location_coverage_report, infer_location_from_item
from app.services.deepseek import DeepSeekClient, DeepSeekError, rule_based_analysis, split_work_item_text
from app.services.dispatch import discover_dispatch_schedules, followup_tracking_to_event
from app.services.feishu import FeishuClient, FeishuError
from app.services.fingerprint import message_fingerprint
from app.services.issues import issue_candidate_from_message, issue_schedule_match_score
from app.services.local_export import export_daily_workbook
from app.services.reminder_text import generate_analysis_reminder_message, generate_reminder_message
from app.services.rules import load_rules_from_xlsx


app = FastAPI(title="WhatsApp Repair AI Backend", version="0.1.0")
logger = logging.getLogger("app.main")
db = Database(settings.database_path)
DOWNLOADS_DIR = settings.downloads_root
AUTO_PIPELINE_LOCK = threading.Lock()
CUSTOMER_SETTINGS_STORE = CustomerSettingsStore(settings.customer_settings_path)
CUSTOMER_SETTINGS: CustomerSettings = CUSTOMER_SETTINGS_STORE.get()
AUTOMATION_NOTICE_MARKERS = ("自动化助手提示",)
ATTACHMENT_LABEL_TEXTS = {
    "前",
    "中",
    "后",
    "後",
    "料",
    "物料",
    "電鎖前",
    "电锁前",
    "電鎖中",
    "电锁中",
    "電鎖後",
    "电锁后",
    "電鎖后",
    "換前",
    "换前",
    "換中",
    "换中",
    "換後",
    "换后",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif"}
PDF_EXTENSIONS = {".pdf"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
DOCUMENT_EXTENSIONS = PDF_EXTENSIONS | {".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv", ".zip", ".rar"}
GENERIC_DOWNLOAD_STEMS = {
    "attachment",
    "attachments",
    "document",
    "download",
    "file",
    "image",
    "img",
    "photo",
    "scan",
    "unknown",
}


def _current_customer_settings() -> CustomerSettings:
    global CUSTOMER_SETTINGS
    current, changed = CUSTOMER_SETTINGS_STORE.refresh()
    CUSTOMER_SETTINGS = current
    if changed:
        _sync_customer_settings_to_database(current)
    return current


def _customer_settings_public_dict(current: CustomerSettings) -> dict[str, object]:
    return {
        "path": current.path or str(settings.customer_settings_path),
        "loaded": current.loaded,
        "error": current.error,
        "validation_errors": current.validation_errors,
        "timezone": current.timezone,
        "whatsapp": {
            "use_current_logged_in_account": current.whatsapp.use_current_logged_in_account,
            "global_scan_lock_enabled": current.whatsapp.global_scan_lock_enabled,
            "watch_groups": current.whatsapp.watch_groups,
            "reminder_sender_account": current.whatsapp.reminder_sender_account,
            "scan_interval_minutes": current.whatsapp.scan_interval_minutes,
            "reminder_interval_minutes": current.whatsapp.reminder_interval_minutes,
            "groups": [
                {
                    "id": group.id,
                    "name": group.name,
                    "enabled": group.enabled,
                    "scan": {
                        "enabled": group.scan.enabled,
                        "interval_minutes": group.scan.interval_minutes,
                        "start_offset_seconds": group.scan.start_offset_seconds,
                        "skip_if_previous_scan_running": group.scan.skip_if_previous_scan_running,
                    },
                    "reminder": {
                        "enabled": group.reminder.enabled,
                        "days_of_week": group.reminder.days_of_week,
                        "times": group.reminder.times,
                        "max_reminders_per_event_per_day": group.reminder.max_reminders_per_event_per_day,
                        "skip_completed_events": group.reminder.skip_completed_events,
                    },
                    "related_site_ids": group.related_site_ids,
                    "related_site_names": current.related_site_names(group),
                }
                for group in current.whatsapp.groups
            ],
        },
        "sites": [
            {
                "id": site.id,
                "name": site.name,
                "aliases": site.aliases,
                "enabled": site.enabled,
            }
            for site in current.sites
        ],
        "event_rules": {
            "completed_keywords": current.event_rules.completed_keywords,
            "pending_keywords": current.event_rules.pending_keywords,
        },
        "photo_record_rules": {
            "enabled": current.photo_record_rules.enabled,
            "require_photo_for_quotation": current.photo_record_rules.require_photo_for_quotation,
            "require_photo_for_replacement": current.photo_record_rules.require_photo_for_replacement,
            "require_pdf_report_for_atal_material": current.photo_record_rules.require_pdf_report_for_atal_material,
            "required_photo_types": current.photo_record_rules.required_photo_types,
        },
    }


def _validation_errors_for_log(exc: RequestValidationError) -> list[dict[str, object]]:
    errors = []
    for error in exc.errors():
        safe_error = {
            key: value
            for key, value in error.items()
            if key not in {"input", "url"}
        }
        errors.append(safe_error)
    return errors


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = _validation_errors_for_log(exc)
    logger.warning(
        "request validation failed status=422 path=%s method=%s errors=%s",
        request.url.path,
        request.method,
        errors,
    )
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    level = logging.WARNING if exc.status_code < 500 else logging.ERROR
    logger.log(
        level,
        "request failed status=%s path=%s method=%s detail=%s",
        exc.status_code,
        request.url.path,
        request.method,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": jsonable_encoder(exc.detail)},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled request error path=%s method=%s",
        request.url.path,
        request.method,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


def deepseek_client() -> DeepSeekClient:
    return DeepSeekClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
    )


def feishu_client() -> FeishuClient:
    return FeishuClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        app_token=settings.feishu_app_token,
        table_id=settings.feishu_table_id,
        base_url=settings.feishu_base_url,
        upload_parent_type=settings.feishu_upload_parent_type,
        upload_parent_node=settings.feishu_upload_parent_node,
    )


def _is_automation_notice(text: str) -> bool:
    return any(marker in text for marker in AUTOMATION_NOTICE_MARKERS)


def _is_standalone_attachment_label(text: str) -> bool:
    normalized = "".join((text or "").split()).strip("：:,.，。()（）[]【】")
    if not normalized:
        return True
    if normalized in ATTACHMENT_LABEL_TEXTS:
        return True
    if len(normalized) <= 2 and normalized in {"前", "中", "后", "後", "料"}:
        return True
    return False


def _apply_staff_mapping(analysis: dict[str, object], message: dict[str, object]) -> dict[str, object]:
    mapped = dict(analysis)
    staff_name = str(mapped.get("staff_name") or "").strip()
    sender = str(message.get("sender") or "").strip()
    mapped_staff = db.resolve_staff_name(staff_name)
    if mapped_staff == staff_name and staff_name == sender:
        mapped_staff = db.resolve_staff_name(sender)
    mapped["staff_name"] = mapped_staff
    return mapped


def _apply_site_mapping(analysis: dict[str, object], message: dict[str, object]) -> dict[str, object]:
    mapped = dict(analysis)
    current_site = str(mapped.get("site") or "").strip()
    if current_site:
        mapped["site"] = db.resolve_site_name(current_site)
        return mapped
    search_text = "\n".join(
        str(value or "")
        for value in (
            mapped.get("summary"),
            mapped.get("result"),
            message.get("text"),
        )
    )
    matched = db.match_site_in_text(search_text)
    if matched:
        mapped["site"] = matched["name"]
    return mapped


def _allowed_attachment_extensions(attachment_type: str) -> set[str] | None:
    if attachment_type == "image":
        return IMAGE_EXTENSIONS
    if attachment_type == "pdf":
        return PDF_EXTENSIONS
    if attachment_type == "video":
        return VIDEO_EXTENSIONS
    if attachment_type == "document":
        return DOCUMENT_EXTENSIONS
    return None


def _find_latest_downloaded_attachment(downloads_root: Path, attachment_type: str) -> tuple[Path | None, int]:
    allowed_extensions = _allowed_attachment_extensions(attachment_type)
    candidates = [
        path
        for path in downloads_root.rglob("*")
        if path.is_file() and (allowed_extensions is None or path.suffix.lower() in allowed_extensions)
    ]
    if not candidates:
        return None, 0
    candidates.sort(key=lambda path: (path.stat().st_mtime, str(path)), reverse=True)
    return candidates[0], len(candidates)


def _default_attachment_filename(
    source_path: Path,
    *,
    attachment_type: str,
    provided_filename: str | None,
    work_date: str | None,
    staff_name: str | None,
) -> str:
    ext = (source_path.suffix or Path(provided_filename or "").suffix or ".bin").lower()
    date_part = safe_part(work_date, "unknown_date")
    staff_part = safe_part(staff_name, "unknown_staff")
    if attachment_type == "image":
        return f"{date_part}_{staff_part}_image{ext}"

    candidate = (provided_filename or "").strip()
    if not candidate:
        candidate = source_path.name
    stem = Path(candidate).stem.strip().casefold()
    if attachment_type == "pdf" and stem and stem not in GENERIC_DOWNLOAD_STEMS:
        return candidate
    if attachment_type == "pdf":
        return f"{date_part}_{staff_part}_pdf{ext if ext else '.pdf'}"
    if candidate:
        return candidate
    return f"{date_part}_{staff_part}_{safe_part(attachment_type, 'attachment')}{ext}"


def _resolve_attachment_source_path(
    payload: AttachmentIn,
    *,
    downloads_root: Path,
) -> tuple[Path, str, int]:
    if payload.temp_path:
        source = Path(payload.temp_path).expanduser()
        return source, "payload_temp_path", 1

    source, candidate_count = _find_latest_downloaded_attachment(downloads_root, payload.attachment_type)
    if source is None:
        raise FileNotFoundError(
            f"no attachment candidate found in downloads directory: {downloads_root}"
        )
    return source, "downloads_root_scan", candidate_count


def _augment_analyses_with_configured_sites(
    analyses: list[dict[str, object]],
    message: dict[str, object],
    attachments: list[dict[str, object]],
    rules: list[dict[str, object]],
) -> list[dict[str, object]]:
    augmented = list(analyses)
    existing_text = "\n".join(
        str(item.get("site") or "") + " " + str(item.get("summary") or "")
        for item in augmented
    ).casefold()
    for chunk in split_work_item_text(str(message.get("text") or "")):
        matched = db.match_site_in_text(chunk)
        if not matched:
            inferred = infer_location_from_item(chunk)
            matched = db.match_site_in_text(inferred)
        if not matched:
            continue
        site_name = str(matched["name"])
        if site_name.casefold() in existing_text and str(chunk[:24]).casefold() in existing_text:
            continue
        if site_name.casefold() in existing_text and _chunk_substance_is_covered(chunk, existing_text):
            continue
        item_message = dict(message)
        item_message["text"] = chunk
        analysis = rule_based_analysis(item_message, attachments, rules)
        analysis["site"] = site_name
        augmented.append(analysis)
        existing_text += "\n" + site_name.casefold() + " " + str(analysis.get("summary") or "").casefold()
    return augmented


def _chunk_substance_is_covered(chunk: str, existing_text: str) -> bool:
    tokens = [part.casefold() for part in str(chunk).replace("/", " ").split() if len(part) >= 3]
    useful = [token for token in tokens if token not in {"the", "and", "正常", "完成"}]
    return bool(useful) and any(token in existing_text for token in useful)


def _ensure_local_directories() -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.customer_settings_path.parent.mkdir(parents=True, exist_ok=True)
    for path in (
        settings.archive_root,
        settings.downloads_root,
        settings.exports_root,
        settings.logs_root,
        settings.backups_root,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _sync_customer_settings_to_database(current: CustomerSettings | None = None) -> None:
    current = current or CUSTOMER_SETTINGS
    if not current.loaded or current.error:
        return
    for site in current.sites:
        db.upsert_site_config(
            {
                "name": site.name,
                "aliases": site.aliases,
                "notes": "customer_settings.json",
                "is_active": site.enabled,
            }
        )


def _group_is_watched(group_name: str) -> bool:
    current = _current_customer_settings()
    watched = current.whatsapp.watch_groups if current.loaded and not current.error else []
    if not watched:
        return True
    normalized = group_name.strip().casefold()
    return any(normalized == item.strip().casefold() for item in watched)


def _match_enabled_customer_site(text: str) -> str:
    current = _current_customer_settings()
    if not current.loaded or current.error:
        return ""
    normalized = str(text or "").casefold()
    for site in current.sites:
        if not site.enabled:
            continue
        candidates = [site.name, *site.aliases]
        if any(candidate and candidate.casefold() in normalized for candidate in candidates):
            return site.name
    return ""


def _site_is_watched_for_reminder(analysis: dict[str, object]) -> bool:
    current = _current_customer_settings()
    enabled_sites = [
        site
        for site in current.sites
        if current.loaded and not current.error and site.enabled
    ]
    if not enabled_sites:
        return True
    text = "\n".join(
        str(analysis.get(key) or "")
        for key in ("site", "summary", "result", "whatsapp_text")
    )
    return bool(_match_enabled_customer_site(text))


def _ensure_due_automation_jobs() -> CustomerSettings:
    current = _current_customer_settings()
    if current.loaded and not current.error:
        db.upsert_automation_jobs(build_due_automation_jobs(current))
    stale_before = (
        datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=STALE_CLAIM_SECONDS)
    ).isoformat()
    db.mark_stale_automation_runs(stale_before)
    return current


def _claim_next_automation_job() -> dict[str, object] | None:
    current = _ensure_due_automation_jobs()
    if not current.loaded or current.error:
        return None
    groups_by_id = {group.id: group for group in current.whatsapp.groups}
    scan_locked = current.whatsapp.global_scan_lock_enabled and db.has_claimed_scan_run()
    for candidate in db.list_automation_run_candidates(limit=50):
        group = groups_by_id.get(str(candidate.get("group_id") or ""))
        if group is None or not group.enabled:
            continue
        if candidate.get("job_type") == SCAN_CYCLE:
            if scan_locked:
                continue
            if group.scan.skip_if_previous_scan_running and db.has_claimed_scan_run_for_group(group.id):
                continue
        run_token = uuid.uuid4().hex
        claimed = db.claim_automation_run(int(candidate["id"]), run_token)
        if claimed:
            return claimed
    return None


def _parse_message_sent_at(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _should_merge_messages(previous: dict[str, object], current: dict[str, object]) -> bool:
    if str(previous.get("group_name") or "") != str(current.get("group_name") or ""):
        return False
    if str(previous.get("sender") or "").strip().casefold() != str(current.get("sender") or "").strip().casefold():
        return False
    previous_sent_at = _parse_message_sent_at(previous.get("sent_at"))
    current_sent_at = _parse_message_sent_at(current.get("sent_at"))
    if previous_sent_at is None or current_sent_at is None:
        return False
    if current_sent_at < previous_sent_at:
        return False
    if (current_sent_at - previous_sent_at).total_seconds() > 180:
        return False
    previous_chunks = split_work_item_text(str(previous.get("text") or "").strip())
    current_chunks = split_work_item_text(str(current.get("text") or "").strip())
    if len(previous_chunks) > 1 or len(current_chunks) > 1:
        return False
    return True


def _merge_message_group(messages: list[dict[str, object]]) -> dict[str, object]:
    merged = dict(messages[0])
    text_parts: list[str] = []
    seen_parts: set[str] = set()
    attachment_hints: list[dict[str, object]] = []
    for message in messages:
        text = str(message.get("text") or "").strip()
        normalized = " ".join(text.split()).casefold()
        if text and normalized not in seen_parts:
            text_parts.append(text)
            seen_parts.add(normalized)
        for hint in message.get("attachment_hints") or []:
            if isinstance(hint, dict):
                attachment_hints.append(hint)
    merged["text"] = "\n".join(text_parts).strip()
    merged["has_attachments"] = any(bool(message.get("has_attachments")) for message in messages)
    merged["attachment_hints"] = attachment_hints
    return merged


def _build_analysis_groups(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for message in messages:
        if not groups or not _should_merge_messages(groups[-1]["messages"][-1], message):
            groups.append({"messages": [message]})
            continue
        groups[-1]["messages"].append(message)
    result: list[dict[str, object]] = []
    for group in groups:
        members = group["messages"]
        result.append(
            {
                "primary": members[0],
                "messages": members,
                "merged_message": _merge_message_group(members),
            }
        )
    return result


def _analyze_messages(messages: list[dict[str, object]], sync_feishu: bool) -> dict[str, object]:
    rules = db.list_rules()
    deepseek = deepseek_client()
    feishu = feishu_client()
    analyzed = 0
    failed = 0
    reminders_created = 0
    feishu_synced = 0
    first_error = None
    records: list[dict[str, object]] = []
    skipped = 0

    for group in _build_analysis_groups(messages):
        primary_message = group["primary"]
        grouped_messages = group["messages"]
        merged_message = group["merged_message"]
        attachments = []
        for grouped_message in grouped_messages:
            attachments.extend(db.list_attachments_for_message(grouped_message["id"]))
        try:
            for grouped_message in grouped_messages:
                db.delete_repair_records_for_message(grouped_message["id"])
            if _is_standalone_attachment_label(str(merged_message.get("text") or "")):
                for grouped_message in grouped_messages:
                    db.mark_message_done(grouped_message["id"])
                skipped += 1
                records.append(
                    {
                        "message_fingerprint": primary_message["message_fingerprint"],
                        "skipped": True,
                        "skip_reason": "standalone_attachment_label",
                    }
                )
                continue
            analyses = deepseek.analyze_message_items(
                message=merged_message,
                attachments=attachments,
                rules=rules,
            )
            analyses = _augment_analyses_with_configured_sites(analyses, merged_message, attachments, rules)
            schedules = db.list_schedules_for_message(merged_message)
            first_feishu_record_id = None
            for item_index, raw_analysis in enumerate(analyses):
                raw_analysis = _apply_staff_mapping(raw_analysis, merged_message)
                raw_analysis = _apply_site_mapping(raw_analysis, merged_message)
                analysis = apply_schedule_completion(
                    analysis=raw_analysis,
                    message=merged_message,
                    attachments=attachments,
                    schedules=schedules,
                )
                analysis["whatsapp_text"] = str(merged_message.get("text") or "").strip()
                feishu_record_id = None
                if sync_feishu and settings.feishu_sync_available:
                    fields = feishu.fields_for_repair_record(merged_message, analysis, attachments)
                    if len(analyses) > 1:
                        fields["WhatsApp原文"] = analysis.get("summary") or merged_message.get("text", "")
                    if feishu.enabled:
                        feishu_record_id = feishu.create_record(fields)
                    else:
                        record_id_for_update = (
                            primary_message.get("feishu_record_id")
                            if item_index == 0 and len(analyses) == 1
                            else None
                        )
                        feishu_record_id = db.save_mock_feishu_record(fields, record_id_for_update)
                    if first_feishu_record_id is None:
                        first_feishu_record_id = feishu_record_id
                    feishu_synced += 1
                record_id = db.save_repair_record(
                    primary_message["id"],
                    analysis,
                    feishu_record_id,
                    item_index=item_index,
                )
                reminder_created = (
                    db.create_reminder_if_needed(record_id, analysis)
                    if _site_is_watched_for_reminder(analysis)
                    else False
                )
                if reminder_created:
                    reminders_created += 1
                records.append(
                    {
                        "message_fingerprint": primary_message["message_fingerprint"],
                        "item_index": item_index,
                        "feishu_record_id": feishu_record_id,
                        "completion_status": analysis.get("completion_status", ""),
                        "completion_score": analysis.get("completion_score", 0),
                        "completion_level": analysis.get("completion_level", ""),
                        "reminders_created": 1 if reminder_created else 0,
                    }
                )
                analyzed += 1
            for grouped_message in grouped_messages:
                db.mark_message_done(grouped_message["id"])
            if len(grouped_messages) > 1:
                for grouped_message in grouped_messages[1:]:
                    records.append(
                        {
                            "message_fingerprint": grouped_message["message_fingerprint"],
                            "merged_into": primary_message["message_fingerprint"],
                        }
                    )
            elif not first_feishu_record_id:
                db.mark_message_done(primary_message["id"])
        except (DeepSeekError, FeishuError, ValueError) as exc:
            for grouped_message in grouped_messages:
                db.mark_message_retry(grouped_message["id"])
            failed += 1
            if first_error is None:
                first_error = str(exc)

    response: dict[str, object] = {
        "processed": len(messages),
        "analyzed": analyzed,
        "failed": failed,
        "skipped": skipped,
        "reminders_created": reminders_created,
        "feishu_synced": feishu_synced,
        "records": records,
    }
    if first_error:
        response["first_error"] = first_error
    return response


def _analyze_pending_messages(limit: int, sync_feishu: bool) -> dict[str, object]:
    return _analyze_messages(db.list_pending_messages(limit), sync_feishu)


def _message_sent_dates(messages: list[dict[str, object]]) -> list[str]:
    dates = {
        _export_date_from_sent_at(str(message.get("sent_at") or ""))
        for message in messages
        if str(message.get("sent_at") or "")
    }
    return sorted(date for date in dates if date)


def _export_date_from_sent_at(value: str) -> str:
    raw = value.strip()
    if len(raw) >= 10 and raw[:4].isdigit() and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    match = re.search(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<year>\d{4})", raw)
    if not match:
        return raw[:10] if len(raw) >= 10 else ""
    first = int(match.group("a"))
    second = int(match.group("b"))
    year = int(match.group("year"))
    day = first
    month = second
    if first <= 12 and second > 12:
        month = first
        day = second
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _export_daily_workbooks_for_messages(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    exports: list[dict[str, object]] = []
    if not settings.auto_export_on_ingest:
        return exports
    for work_date in _message_sent_dates(messages):
        result = export_daily_workbook(
            db=db,
            work_date=work_date,
            export_root=settings.exports_root,
        )
        exports.append(
            {
                "work_date": work_date,
                "total_path": result.total_path,
                "site_paths": result.site_paths,
                "site_count": len(result.site_paths),
            }
        )
    return exports


def _run_post_ingest_pipeline(fingerprints: list[str]) -> dict[str, object]:
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    unique_fingerprints = list(dict.fromkeys(fingerprints))
    if not unique_fingerprints:
        return {
            "ok": True,
            "run_id": run_id,
            "processed": 0,
            "analyzed": 0,
            "exports": [],
        }

    with AUTO_PIPELINE_LOCK:
        messages = db.list_messages_by_fingerprints(unique_fingerprints)
        pending_messages = [
            message
            for message in messages
            if str(message.get("analysis_status") or "pending") in {"pending", "retry"}
        ]
        try:
            analysis_result = _analyze_messages(
                pending_messages,
                sync_feishu=settings.auto_sync_feishu_on_ingest,
            )
            refreshed_messages = db.list_messages_by_fingerprints(unique_fingerprints)
            exports = _export_daily_workbooks_for_messages(refreshed_messages)
            status = "success" if analysis_result.get("failed", 0) == 0 else "failed"
            db.save_run_record(
                {
                    "run_id": run_id,
                    "run_type": "auto_ingest_pipeline",
                    "status": status,
                    "message_summary": (
                        f"影刀入库自动处理：消息 {len(messages)} 条，"
                        f"分析 {analysis_result.get('analyzed', 0)} 条，"
                        f"导出 {len(exports)} 个日期"
                    ),
                    "inserted_count": len(messages),
                    "analyzed_count": analysis_result.get("analyzed", 0),
                    "feishu_synced_count": analysis_result.get("feishu_synced", 0),
                    "reminders_created": analysis_result.get("reminders_created", 0),
                    "error_summary": analysis_result.get("first_error"),
                }
            )
            return {
                "ok": status == "success",
                "run_id": run_id,
                "messages": len(messages),
                "pending_messages": len(pending_messages),
                "analysis": analysis_result,
                "exports": exports,
            }
        except Exception as exc:
            db.save_run_record(
                {
                    "run_id": run_id,
                    "run_type": "auto_ingest_pipeline",
                    "status": "failed",
                    "message_summary": f"影刀入库自动处理失败：消息 {len(messages)} 条",
                    "inserted_count": len(messages),
                    "error_summary": str(exc)[:240],
                }
            )
            return {
                "ok": False,
                "run_id": run_id,
                "messages": len(messages),
                "pending_messages": len(pending_messages),
                "analysis": {"failed": len(pending_messages), "first_error": str(exc)},
                "exports": [],
            }


def _schedule_post_ingest_pipeline(
    *,
    fingerprints: list[str],
    background_tasks: BackgroundTasks | None,
) -> dict[str, object]:
    if not settings.auto_analyze_on_ingest:
        return {"scheduled": False, "reason": "AUTO_ANALYZE_ON_INGEST is disabled"}
    unique_fingerprints = list(dict.fromkeys(fingerprints))
    if not unique_fingerprints:
        return {"scheduled": False, "reason": "no messages to analyze"}
    if background_tasks is None:
        return {"scheduled": False, "reason": "no background task runner"}
    if background_tasks is not None and settings.auto_pipeline_background:
        background_tasks.add_task(_run_post_ingest_pipeline, unique_fingerprints)
        return {
            "scheduled": True,
            "background": True,
            "message_count": len(unique_fingerprints),
        }
    result = _run_post_ingest_pipeline(unique_fingerprints)
    return {"scheduled": True, "background": False, "result": result}


def _role_senders(role: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    configured = db.list_staff_names_for_role(role)
    if db.has_staff_configs():
        return tuple(configured)
    return tuple(configured) if configured else fallback


def _sync_schedule_gap(
    schedule: dict[str, object],
    feishu: FeishuClient,
) -> dict[str, object]:
    analysis = schedule_gap_analysis(schedule)
    message = {
        "sender": schedule["staff_name"],
        "sent_at": f"{schedule['work_date']} 23:59",
        "text": "",
        "feishu_record_id": None,
    }
    feishu_record_id = None
    if settings.feishu_sync_available:
        fields = feishu.fields_for_repair_record(message, analysis, [])
        if feishu.enabled:
            feishu_record_id = feishu.create_record(fields)
        else:
            feishu_record_id = db.save_mock_feishu_record(fields)
    record_id = db.save_schedule_gap_record(schedule, analysis, feishu_record_id)
    reminder_created = (
        db.create_reminder_if_needed(record_id, analysis)
        if _site_is_watched_for_reminder(analysis)
        else False
    )
    return {
        "repair_record_id": record_id,
        "work_schedule_id": schedule["id"],
        "staff_name": schedule["staff_name"],
        "site": schedule.get("site"),
        "completion_status": analysis["completion_status"],
        "completion_score": analysis.get("completion_score", 0),
        "completion_level": analysis.get("completion_level", ""),
        "mock_feishu_record_id": feishu_record_id,
        "reminder_created": reminder_created,
    }


def _repair_record_followup_analysis(record: dict[str, object]) -> dict[str, object]:
    missing_items = list(record.get("missing_items") or [])
    next_actions = list(record.get("next_actions") or [])
    status = str(record.get("completion_status") or "")
    staff_name = str(record.get("staff_name") or "相关同事")
    site = str(record.get("site") or "")
    task_text = str(record.get("task_text") or "")
    analysis = {
        "work_schedule_id": record.get("work_schedule_id"),
        "work_date": record.get("work_date"),
        "staff_name": staff_name,
        "site": site,
        "work_type": record.get("work_type"),
        "task_text": task_text,
        "summary": record.get("summary") or "",
        "result": record.get("result") or "",
        "completion_status": status,
        "completion_score": record.get("completion_score", 0),
        "completion_level": record.get("completion_level", ""),
        "missing_items": missing_items,
        "next_actions": next_actions,
    }
    analysis["reminder_text"] = generate_analysis_reminder_message(analysis)
    analysis["whatsapp_text"] = str(record.get("whatsapp_text") or "").strip()
    return analysis


def _run_auto_followups(work_date: str, limit: int, site_names: list[str] | None = None) -> dict[str, object]:
    feishu = feishu_client()
    schedule_records = []
    existing_record_items = []
    reminders_created = 0
    feishu_synced = 0

    schedules = db.list_schedules_without_repair_records(work_date, limit, site_names=site_names)
    for schedule in schedules:
        item = _sync_schedule_gap(schedule, feishu)
        if item.get("mock_feishu_record_id"):
            feishu_synced += 1
        if item["reminder_created"]:
            reminders_created += 1
        schedule_records.append(item)

    remaining_limit = max(0, limit - len(schedules))
    repair_records = (
        db.list_repair_records_needing_followup(work_date=work_date, limit=remaining_limit, site_names=site_names)
        if remaining_limit
        else []
    )
    for record in repair_records:
        analysis = _repair_record_followup_analysis(record)
        reminder_created = (
            db.create_reminder_if_needed(int(record["id"]), analysis)
            if _site_is_watched_for_reminder(analysis)
            else False
        )
        if reminder_created:
            reminders_created += 1
        existing_record_items.append(
            {
                "repair_record_id": record["id"],
                "work_schedule_id": record.get("work_schedule_id"),
                "staff_name": record.get("staff_name"),
                "site": record.get("site"),
                "completion_status": record.get("completion_status"),
                "completion_score": record.get("completion_score", 0),
                "completion_level": record.get("completion_level", ""),
                "missing_items": record.get("missing_items", []),
                "next_actions": record.get("next_actions", []),
                "reminder_created": reminder_created,
            }
        )

    return {
        "work_date": work_date,
        "site_names": site_names or [],
        "checked_schedules": len(schedules),
        "checked_repair_records": len(repair_records),
        "reminders_created": reminders_created,
        "feishu_synced": feishu_synced,
        "schedule_gap_records": schedule_records,
        "repair_record_followups": existing_record_items,
    }


def _auto_convert_issues_for_schedules(schedules: list[dict[str, object]]) -> list[dict[str, object]]:
    converted = []
    used_issue_ids: set[int] = set()
    for schedule in schedules:
        saved_schedule = db.find_schedule_row(schedule) or schedule
        schedule_id = saved_schedule.get("id")
        if not schedule_id:
            continue
        candidates = db.list_pending_issue_candidates(
            site=str(saved_schedule.get("site") or ""),
            limit=20,
        )
        best_issue = None
        best_score = 0
        for issue in candidates:
            issue_id = int(issue["id"])
            if issue_id in used_issue_ids:
                continue
            score = issue_schedule_match_score(issue, saved_schedule)
            if score > best_score:
                best_issue = issue
                best_score = score
        if best_issue and best_score >= 7:
            result = db.link_issue_to_schedule(
                int(best_issue["id"]),
                int(schedule_id),
                note=f"系统根据派工消息自动转任务，匹配分数 {best_score}",
            )
            if result.get("linked"):
                used_issue_ids.add(int(best_issue["id"]))
                converted.append(
                    {
                        "issue_id": best_issue["id"],
                        "work_schedule_id": schedule_id,
                        "reported_by": best_issue.get("reported_by"),
                        "site": best_issue.get("site"),
                        "issue_summary": best_issue.get("issue_summary"),
                        "task_text": saved_schedule.get("task_text"),
                        "match_score": best_score,
                    }
                )
    return converted


def _discover_and_save_dispatch_schedules(messages: list[dict[str, object]]) -> dict[str, object]:
    followup_marked = 0
    followup_events = []
    issue_records = []
    dispatch_senders = _role_senders(
        "dispatch_manager",
        settings.dispatch_manager_senders,
    )
    followup_senders = _role_senders(
        "followup_manager",
        settings.followup_manager_senders,
    )
    for message in messages:
        event = followup_tracking_to_event(
            message,
            followup_manager_senders=followup_senders,
        )
        if event:
            matched_schedule = db.find_schedule_for_event(
                work_date=event.get("work_date"),
                target_name=event.get("target_name"),
                site=event.get("site"),
            )
            if matched_schedule:
                event["work_schedule_id"] = matched_schedule["id"]
            saved_event = db.save_task_event(event)
            db.mark_message_done(int(message["id"]))
            followup_marked += 1
            followup_events.append(
                {
                    "id": saved_event.get("id"),
                    "inserted": saved_event.get("inserted"),
                    "event_type": event["event_type"],
                    "target_name": event.get("target_name"),
                    "site": event.get("site"),
                    "work_date": event.get("work_date"),
                    "work_schedule_id": event.get("work_schedule_id"),
                }
            )
            continue
        issue = issue_candidate_from_message(
            message,
            dispatch_manager_senders=dispatch_senders,
            followup_manager_senders=followup_senders,
        )
        if issue:
            saved_issue = db.save_issue_record(issue)
            db.mark_message_done(int(message["id"]))
            issue_records.append(
                {
                    "id": saved_issue.get("id"),
                    "inserted": saved_issue.get("inserted"),
                    "reported_by": issue.get("reported_by"),
                    "site": issue.get("site"),
                    "work_date": issue.get("work_date"),
                    "issue_summary": issue.get("issue_summary"),
                }
            )
    schedules = discover_dispatch_schedules(
        messages,
        dispatch_manager_senders=dispatch_senders,
    )
    if not schedules:
        return {
            "candidates": 0,
            "inserted": 0,
            "skipped": 0,
            "marked_messages": 0,
            "followup_marked_messages": followup_marked,
            "followup_events": followup_events,
            "issue_records": issue_records,
            "auto_converted_issues": [],
            "schedules": [],
        }
    result = db.insert_schedule_rows(schedules)
    auto_converted_issues = _auto_convert_issues_for_schedules(schedules)
    marked = 0
    for schedule in schedules:
        raw_message_id = schedule.get("raw_message_id")
        if raw_message_id:
            db.mark_message_done(int(raw_message_id))
            marked += 1
    return {
        "candidates": len(schedules),
        "inserted": result.get("inserted", 0),
        "skipped": result.get("skipped", 0),
        "marked_messages": marked,
        "followup_marked_messages": followup_marked,
        "followup_events": followup_events,
        "issue_records": issue_records,
        "auto_converted_issues": auto_converted_issues,
        "schedules": [
            {
                "work_date": item["work_date"],
                "staff_name": item["staff_name"],
                "site": item["site"],
                "task_text": item["task_text"],
                "source_file": item["source_file"],
            }
            for item in schedules
        ],
    }


def _mock_attachment_type(hints: list[dict[str, object]]) -> str:
    if hints:
        value = hints[0].get("type")
        if value in {"image", "pdf", "video", "document", "other"}:
            return str(value)
    return "image"


def _create_manual_mock_attachments(
    *,
    fingerprint: str,
    sender: str,
    sent_at: str,
    attachment_hints: list[dict[str, object]],
) -> int:
    message = db.get_message_by_fingerprint(fingerprint)
    if not message:
        return 0
    hints = attachment_hints or [{"type": _mock_attachment_type([]), "label": "mock_attachment"}]
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    inserted = 0
    for index, hint in enumerate(hints, start=1):
        attachment_type = str(hint.get("type") or _mock_attachment_type([]))
        extension = ".pdf" if attachment_type == "pdf" else ".jpg"
        label = str(hint.get("label") or hint.get("role") or f"mock_{index}")
        temp_path = DOWNLOADS_DIR / f"{fingerprint[:12]}_{index}_{label}{extension}"
        if not temp_path.exists():
            temp_path.write_bytes(f"manual mock attachment for {fingerprint} {label}\n".encode("utf-8"))
        archived = archive_attachment(
            str(temp_path),
            settings.archive_root,
            original_filename=temp_path.name,
            work_date=sent_at[:10],
            site="mock_site",
            staff_name=sender,
            work_type="mock_work",
            attachment_type=attachment_type,
        )
        if db.insert_attachment(
            {
                "raw_message_id": message["id"],
                "original_filename": archived.original_filename,
                "original_path": archived.original_path,
                "archive_filename": archived.archive_filename,
                "archive_path": archived.archive_path,
                "attachment_type": attachment_type,
                "sha256": archived.sha256,
                "size_bytes": archived.size_bytes,
            }
        ):
            inserted += 1
    return inserted


@app.on_event("startup")
def startup() -> None:
    _ensure_local_directories()
    log_path = configure_backend_logging(settings.logs_root)
    logger.info("backend startup log_path=%s", log_path)
    db.init()
    _sync_customer_settings_to_database(_current_customer_settings())


@app.get("/health")
def health() -> dict[str, object]:
    current = _current_customer_settings()
    return {
        "ok": True,
        "database": str(settings.database_path),
        "deepseek_enabled": settings.deepseek_enabled,
        "feishu_enabled": settings.feishu_enabled,
        "feishu_mock_mode": settings.feishu_mock_mode,
        "feishu_sync_available": settings.feishu_sync_available,
        "customer_settings": {
            "path": current.path or str(settings.customer_settings_path),
            "loaded": current.loaded,
            "error": current.error,
            "watch_groups": current.whatsapp.watch_groups,
            "reminder_sender_account": current.whatsapp.reminder_sender_account,
            "scan_interval_minutes": current.whatsapp.scan_interval_minutes,
            "reminder_interval_minutes": current.whatsapp.reminder_interval_minutes,
            "sites_count": len(current.sites),
            "groups_count": len(current.whatsapp.groups),
        },
    }


@app.get("/api/config/customer")
def customer_config() -> dict[str, object]:
    return _customer_settings_public_dict(_current_customer_settings())


@app.get("/api/automation/next")
def next_automation_job() -> dict[str, object]:
    current = _current_customer_settings()
    if not current.loaded:
        return {
            "job": None,
            "config": {
                "loaded": current.loaded,
                "error": current.error,
                "validation_errors": current.validation_errors,
            },
        }
    job = _claim_next_automation_job()
    if not job:
        return {
            "job": None,
            "config": {
                "loaded": current.loaded,
                "timezone": current.timezone,
                "watch_groups": current.whatsapp.watch_groups,
            },
        }
    return {
        "job": {
            "run_token": job.get("run_token"),
            "job_type": job.get("job_type"),
            "group_id": job.get("group_id"),
            "group_name": job.get("group_name"),
            "scheduled_for": job.get("scheduled_for"),
            "timezone": job.get("timezone"),
            "site_names": job.get("site_names", []),
            "actions": job.get("actions", []),
            "skip_if_previous_scan_running": job.get("skip_if_previous_scan_running", True),
            "max_reminders_per_event_per_day": job.get("max_reminders_per_event_per_day", 1),
            "skip_completed_events": job.get("skip_completed_events", True),
            "reminder_sender_account": current.whatsapp.reminder_sender_account,
        }
    }


@app.post("/api/automation/report")
def automation_report(payload: AutomationReportIn) -> dict[str, bool]:
    saved = db.save_automation_run_result(
        run_token=payload.run_token,
        status=payload.status,
        result_payload=payload.result_payload,
        error_summary=payload.error_summary,
    )
    if not saved:
        raise HTTPException(status_code=404, detail="automation run token not found")
    return {"ok": True}


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings() -> str:
    return admin_settings_html()


@app.get("/api/admin/staff")
def admin_list_staff() -> dict[str, object]:
    return {
        "staff": db.list_staff_configs(),
        "roles": [
            {"value": "dispatch_manager", "label": "派工人员"},
            {"value": "followup_manager", "label": "跟进/验收"},
            {"value": "technician", "label": "维修执行"},
            {"value": "issue_reporter", "label": "问题上报"},
            {"value": "viewer", "label": "管理查看"},
        ],
    }


@app.post("/api/admin/staff")
def admin_save_staff(payload: StaffConfigIn) -> dict[str, object]:
    staff_id = db.upsert_staff_config(payload.model_dump())
    return {"ok": True, "id": staff_id}


@app.patch("/api/admin/staff/{staff_id}/active")
def admin_set_staff_active(staff_id: int, payload: StaffActiveIn) -> dict[str, object]:
    updated = db.set_staff_active(staff_id, payload.is_active)
    if not updated:
        raise HTTPException(status_code=404, detail="staff not found")
    return {"ok": True}


@app.get("/api/admin/sites")
def admin_list_sites() -> dict[str, object]:
    return {"sites": db.list_site_configs()}


@app.post("/api/admin/sites")
def admin_save_site(payload: SiteConfigIn) -> dict[str, object]:
    site_id = db.upsert_site_config(payload.model_dump())
    return {"ok": True, "id": site_id}


@app.patch("/api/admin/sites/{site_id}/active")
def admin_set_site_active(site_id: int, payload: SiteActiveIn) -> dict[str, object]:
    updated = db.set_site_active(site_id, payload.is_active)
    if not updated:
        raise HTTPException(status_code=404, detail="site not found")
    return {"ok": True}


@app.get("/api/admin/principles")
def admin_list_principles() -> dict[str, object]:
    return {"principles": db.list_system_principles()}


@app.put("/api/admin/principles")
def admin_update_principles(payload: SystemPrinciplesIn) -> dict[str, object]:
    db.update_system_principles(payload.principles)
    return {"ok": True, "principles": db.list_system_principles()}


@app.get("/api/issues")
def list_issues(
    status: str = Query(default="pending"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    return {"issues": db.list_issue_records(status=status, limit=limit)}


@app.post("/api/issues/{issue_id}/convert")
def convert_issue(issue_id: int, payload: IssueConvertIn) -> dict[str, object]:
    result = db.convert_issue_to_schedule(
        issue_id,
        {
            "work_date": payload.work_date,
            "shift": payload.shift,
            "staff_name": payload.staff_name,
            "site": payload.site,
            "task_text": payload.task_text,
            "source_file": f"issue_record:{issue_id}",
            "ocr_confidence": 0.9,
            "review_status": "confirmed",
        },
        note=payload.note,
    )
    if result.get("reason") == "issue_not_found":
        raise HTTPException(status_code=404, detail="issue not found")
    return {"ok": bool(result.get("converted")), **result}


@app.post("/api/issues/{issue_id}/ignore")
def ignore_issue(issue_id: int, payload: IssueDecisionIn) -> dict[str, object]:
    updated = db.update_issue_status(issue_id, "ignored", payload.note)
    if not updated:
        raise HTTPException(status_code=404, detail="issue not found")
    return {"ok": True}


@app.post("/api/issues/{issue_id}/close")
def close_issue(issue_id: int, payload: IssueDecisionIn) -> dict[str, object]:
    updated = db.update_issue_status(issue_id, "closed", payload.note)
    if not updated:
        raise HTTPException(status_code=404, detail="issue not found")
    return {"ok": True}


def ingest_whatsapp_messages(
    payload: WhatsAppMessageBatchIn,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, object]:
    if not _group_is_watched(payload.group_name):
        return {
            "messages": {"inserted": 0, "skipped": 0, "filtered": len(payload.messages)},
            "dispatch_schedules": {
                "candidates": 0,
                "inserted": 0,
                "skipped": 0,
                "marked_messages": 0,
                "followup_marked_messages": 0,
                "followup_events": 0,
                "issue_records": 0,
                "auto_converted_issues": [],
                "schedules": [],
            },
            "auto_pipeline": {"scheduled": False, "reason": "ignored unwatched group"},
        }
    rows = []
    fingerprints = []
    filtered = 0
    for message in payload.messages:
        if _is_automation_notice(message.text):
            filtered += 1
            continue
        fingerprint = message_fingerprint(
            group_name=payload.group_name,
            sender=message.sender,
            sent_at=message.sent_at,
            text=message.text,
            external_message_id=message.external_message_id,
            attachment_hints=message.attachment_hints,
        )
        fingerprints.append(fingerprint)
        rows.append(
            {
                "group_name": payload.group_name,
                "sender": message.sender,
                "sent_at": message.sent_at,
                "text": message.text,
                "external_message_id": message.external_message_id,
                "attachment_hints": message.attachment_hints,
                "raw_payload": message.raw_payload,
                "has_attachments": message.has_attachments,
                "message_fingerprint": fingerprint,
            }
        )
    existing_messages = db.list_messages_by_fingerprints(fingerprints)
    existing_fingerprints = {
        str(message.get("message_fingerprint") or "")
        for message in existing_messages
    }
    new_fingerprints = [
        fingerprint
        for fingerprint in fingerprints
        if fingerprint not in existing_fingerprints
    ]

    insert_result = db.insert_messages(rows)
    insert_result["filtered"] = filtered
    new_messages = db.list_messages_by_fingerprints(new_fingerprints)
    dispatch_result = _discover_and_save_dispatch_schedules(new_messages)
    auto_pipeline = {"scheduled": False, "reason": "no newly inserted messages"}
    if new_messages:
        auto_pipeline = _schedule_post_ingest_pipeline(
            fingerprints=new_fingerprints,
            background_tasks=background_tasks,
        )
    return {
        "messages": insert_result,
        "dispatch_schedules": dispatch_result,
        "auto_pipeline": auto_pipeline,
    }


@app.post("/api/whatsapp/messages")
def ingest_whatsapp_messages_route(
    payload: WhatsAppMessageBatchIn,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    return ingest_whatsapp_messages(payload, background_tasks)


@app.post("/api/mock/whatsapp/message")
def ingest_mock_whatsapp_message(payload: MockWhatsAppMessageIn) -> dict[str, object]:
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    sent_at = payload.sent_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    group_name = payload.group_name or settings.whatsapp_group_name or "Mock维修工作群"
    external_message_id = f"manual-mock-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    fingerprint = message_fingerprint(
        group_name=group_name,
        sender=payload.sender,
        sent_at=sent_at,
        text=payload.text,
        external_message_id=external_message_id,
        attachment_hints=payload.attachment_hints,
    )
    insert_result = db.insert_messages(
        [
            {
                "group_name": group_name,
                "sender": payload.sender,
                "sent_at": sent_at,
                "text": payload.text,
                "external_message_id": external_message_id,
                "attachment_hints": payload.attachment_hints,
                "raw_payload": {"source": "manual_mock"},
                "has_attachments": payload.has_attachments,
                "message_fingerprint": fingerprint,
            }
        ]
    )
    attachments_inserted = 0
    if payload.has_attachments and insert_result["inserted"]:
        attachments_inserted = _create_manual_mock_attachments(
            fingerprint=fingerprint,
            sender=payload.sender,
            sent_at=sent_at,
            attachment_hints=payload.attachment_hints,
        )
    message = db.get_message_by_fingerprint(fingerprint)
    analysis_result = _analyze_messages([message], sync_feishu=True) if message else {
        "processed": 0,
        "analyzed": 0,
        "failed": 1,
        "reminders_created": 0,
        "feishu_synced": 0,
        "records": [],
        "first_error": "message was not found after insert",
    }
    first_record = (analysis_result.get("records") or [{}])[0]
    status = "success" if analysis_result.get("failed") == 0 else "failed"
    run_record = {
        "run_id": run_id,
        "run_type": "mock_message",
        "status": status,
        "sender": payload.sender,
        "message_summary": payload.text[:160],
        "message_fingerprint": fingerprint,
        "mock_feishu_record_id": first_record.get("feishu_record_id"),
        "inserted_count": insert_result["inserted"],
        "analyzed_count": analysis_result.get("analyzed", 0),
        "feishu_synced_count": analysis_result.get("feishu_synced", 0),
        "reminders_created": analysis_result.get("reminders_created", 0),
        "error_summary": analysis_result.get("first_error"),
    }
    db.save_run_record(run_record)
    return {
        "ok": status == "success",
        "run_id": run_id,
        "run_status": status,
        "completion_status": first_record.get("completion_status", ""),
        "completion_score": first_record.get("completion_score", 0),
        "completion_level": first_record.get("completion_level", ""),
        "sender": payload.sender,
        "message_fingerprint": fingerprint,
        "insert": insert_result,
        "attachments_inserted": attachments_inserted,
        "mock_feishu_record_id": first_record.get("feishu_record_id"),
        "reminders_created": analysis_result.get("reminders_created", 0),
    }


@app.get("/api/whatsapp/download-jobs")
def whatsapp_download_jobs(
    limit: int = Query(default=50, ge=1, le=500),
    group_name: str | None = Query(default=None),
) -> dict[str, object]:
    jobs = []
    for job in db.list_download_jobs(limit, group_name=group_name):
        work_date = _export_date_from_sent_at(str(job.get("sent_at") or "")) or str(job.get("work_date") or "")
        site = str(job.get("site") or "unknown_site")
        job["suggested_download_dir"] = str(
            settings.downloads_root
            / safe_part(site, "unknown_site")
            / safe_part(work_date, "unknown_date")
        )
        jobs.append(job)
    return {"jobs": jobs}


@app.get("/api/whatsapp/messages/recent")
def recent_whatsapp_messages(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    return {"messages": db.list_recent_messages(limit)}


@app.get("/api/status")
def status() -> dict[str, object]:
    return {
        "health": health(),
        "counts": db.count_rows(),
    }


@app.post("/api/exports/daily")
def export_daily(work_date: str = Query(min_length=10, max_length=10)) -> dict[str, object]:
    result = export_daily_workbook(
        db=db,
        work_date=work_date,
        export_root=settings.exports_root,
    )
    return {
        "work_date": work_date,
        "total_path": result.total_path,
        "site_paths": result.site_paths,
        "site_count": len(result.site_paths),
    }


@app.get("/api/exports/diagnostics")
def export_diagnostics(work_date: str = Query(min_length=10, max_length=10)) -> dict[str, object]:
    return build_location_coverage_report(
        messages=db.list_messages_for_date(work_date),
        repair_records=db.list_export_repair_records(work_date),
    )


@app.get("/api/runs/recent")
def recent_runs(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    return {"runs": db.list_run_records(limit)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, object]:
    record = db.get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="run_id not found")
    return {"run": record}


@app.get("/api/mock/feishu/records")
def mock_feishu_records(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    return {"records": db.list_mock_feishu_records(limit)}


@app.get("/api/task-events/recent")
def recent_task_events(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    return {"events": db.list_task_events(limit)}


@app.post("/api/whatsapp/attachments")
def ingest_attachment(
    payload: AttachmentIn,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    message = None
    if payload.message_fingerprint:
        message = db.get_message_by_fingerprint(payload.message_fingerprint)
    if not message and payload.external_message_id:
        message = db.get_message_by_external_id(payload.external_message_id)
    if not message:
        logger.warning(
            "attachment message reference not found external_message_id=%s message_fingerprint=%s",
            payload.external_message_id,
            payload.message_fingerprint,
        )
        raise HTTPException(status_code=404, detail="message reference not found")
    repair_records = db.list_repair_records_for_message(message["id"])
    matched_record = repair_records[0] if repair_records else {}
    export_date = _export_date_from_sent_at(str(message.get("sent_at") or ""))
    work_date = payload.work_date or export_date or matched_record.get("work_date") or message["sent_at"][:10]
    site = payload.site or matched_record.get("site")
    staff_name = payload.staff_name or matched_record.get("staff_name") or message["sender"]
    work_type = payload.work_type or matched_record.get("work_type")
    logger.info(
        "attachment ingest received external_message_id=%s message_fingerprint=%s "
        "original_filename=%s temp_path=%s attachment_type=%s resolved_work_date=%s resolved_site=%s resolved_staff=%s",
        payload.external_message_id,
        payload.message_fingerprint,
        payload.original_filename,
        payload.temp_path,
        payload.attachment_type,
        work_date,
        site,
        staff_name,
    )
    try:
        source_path, source_strategy, candidate_count = _resolve_attachment_source_path(
            payload,
            downloads_root=settings.downloads_root,
        )
        original_filename = _default_attachment_filename(
            source_path,
            attachment_type=payload.attachment_type,
            provided_filename=payload.original_filename,
            work_date=str(work_date) if work_date else None,
            staff_name=str(staff_name) if staff_name else None,
        )
        logger.info(
            "attachment source resolved external_message_id=%s message_fingerprint=%s "
            "strategy=%s candidates=%s source_path=%s original_filename=%s",
            payload.external_message_id,
            payload.message_fingerprint,
            source_strategy,
            candidate_count,
            source_path,
            original_filename,
        )
        archived = archive_attachment(
            str(source_path),
            settings.archive_root,
            original_filename=original_filename,
            work_date=str(work_date) if work_date else None,
            site=str(site) if site else None,
            staff_name=str(staff_name) if staff_name else None,
            work_type=str(work_type) if work_type else None,
            attachment_type=payload.attachment_type,
        )
    except FileNotFoundError as exc:
        logger.warning(
            "attachment file not found external_message_id=%s message_fingerprint=%s "
            "temp_path=%s downloads_root=%s detail=%s",
            payload.external_message_id,
            payload.message_fingerprint,
            payload.temp_path,
            settings.downloads_root,
            exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    inserted = db.insert_attachment(
        {
            "raw_message_id": message["id"],
            "original_filename": archived.original_filename,
            "original_path": archived.original_path,
            "archive_filename": archived.archive_filename,
            "archive_path": archived.archive_path,
            "attachment_type": payload.attachment_type,
            "sha256": archived.sha256,
            "size_bytes": archived.size_bytes,
        }
    )
    auto_pipeline = {"scheduled": False, "reason": "attachment was already archived"}
    if inserted:
        db.mark_message_retry(message["id"])
        auto_pipeline = _schedule_post_ingest_pipeline(
            fingerprints=[message["message_fingerprint"]],
            background_tasks=background_tasks,
        )
    logger.info(
        "attachment archived inserted=%s external_message_id=%s message_fingerprint=%s "
        "archive_path=%s archive_filename=%s sha256=%s",
        inserted,
        payload.external_message_id,
        payload.message_fingerprint,
        archived.archive_path,
        archived.archive_filename,
        archived.sha256,
    )
    return {
        "inserted": inserted,
        "archive_path": archived.archive_path,
        "archive_filename": archived.archive_filename,
        "sha256": archived.sha256,
        "auto_pipeline": auto_pipeline,
    }


@app.post("/api/rules/import")
def import_rules(payload: RuleImportIn) -> dict[str, int]:
    try:
        rules = load_rules_from_xlsx(payload.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return db.upsert_rules(rules)


@app.post("/api/schedules/import")
def import_schedules(payload: ScheduleImportIn) -> dict[str, int]:
    rows = [row.model_dump() for row in payload.rows]
    return db.insert_schedule_rows(rows)


@app.post("/api/schedules/discover-from-messages")
def discover_schedules_from_messages(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    messages = db.list_recent_messages(limit)
    return _discover_and_save_dispatch_schedules(messages)


@app.post("/api/schedules/check-unreplied")
def check_unreplied_schedules(work_date: str = Query(min_length=10), limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    created = 0
    schedules = db.list_schedules_without_repair_records(work_date, limit)
    records: list[dict[str, object]] = []
    feishu = feishu_client()
    for schedule in schedules:
        item = _sync_schedule_gap(schedule, feishu)
        reminder_created = bool(item["reminder_created"])
        created += 1 if reminder_created else 0
        records.append(item)
    return {"checked": len(schedules), "reminders_created": created, "records": records}


@app.post("/api/followups/run")
def run_followups(
    work_date: str | None = Query(default=None, min_length=10),
    limit: int = Query(default=100, ge=1, le=500),
    site_names: str | None = Query(default=None),
) -> dict[str, object]:
    target_date = work_date or datetime.now().strftime("%Y-%m-%d")
    parsed_site_names = parse_site_names_csv(site_names)
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    try:
        result = _run_auto_followups(target_date, limit, site_names=parsed_site_names)
        db.save_run_record(
            {
                "run_id": run_id,
                "run_type": "auto_followup",
                "status": "success",
                "message_summary": (
                    f"{target_date} 自动检查：计划未回复 {result['checked_schedules']} 条，"
                    f"资料不足/需跟进 {result['checked_repair_records']} 条"
                ),
                "analyzed_count": int(result["checked_schedules"]) + int(result["checked_repair_records"]),
                "feishu_synced_count": result["feishu_synced"],
                "reminders_created": result["reminders_created"],
            }
        )
        return {"ok": True, "run_id": run_id, **result}
    except (FeishuError, ValueError) as exc:
        db.save_run_record(
            {
                "run_id": run_id,
                "run_type": "auto_followup",
                "status": "failed",
                "message_summary": f"{target_date} 自动跟进失败",
                "error_summary": str(exc)[:240],
            }
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/analyze/run")
def run_analysis(payload: AnalyzeRunIn) -> dict[str, object]:
    return _analyze_pending_messages(payload.limit, payload.sync_feishu)


@app.post("/api/analyze/reset")
def reset_analysis(payload: AnalyzeResetIn) -> dict[str, object]:
    reset = 0
    for message_id in payload.message_ids:
        db.mark_message_retry(message_id)
        reset += 1
    return {"reset": reset, "message_ids": payload.message_ids}


@app.post("/api/analyze/cleanup-label-records")
def cleanup_label_records() -> dict[str, object]:
    return db.cleanup_mock_records_by_whatsapp_texts(ATTACHMENT_LABEL_TEXTS)


@app.get("/api/reminders/pending")
def pending_reminders(
    limit: int = Query(default=50, ge=1, le=500),
    site_names: str | None = Query(default=None),
) -> dict[str, object]:
    return {"reminders": db.list_pending_reminders(limit, parse_site_names_csv(site_names))}


@app.post("/api/reminders/preview")
def preview_reminder(payload: ReminderPreviewIn) -> dict[str, str]:
    return {"message": generate_reminder_message(payload.model_dump())}


@app.post("/api/reminders/result")
def reminder_result(payload: ReminderResultIn) -> dict[str, bool]:
    db.save_reminder_result(
        payload.reminder_id,
        payload.status,
        payload.result_payload,
    )
    return {"ok": True}
