from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.admin_ui import admin_settings_html
from app.config import settings
from app.database import Database
from app.schemas import (
    AnalyzeRunIn,
    AttachmentIn,
    IssueConvertIn,
    IssueDecisionIn,
    MockWhatsAppMessageIn,
    ReminderResultIn,
    RuleImportIn,
    ScheduleImportIn,
    StaffActiveIn,
    StaffConfigIn,
    SystemPrinciplesIn,
    WhatsAppMessageBatchIn,
)
from app.services.archive import archive_attachment
from app.services.completion import apply_schedule_completion, schedule_gap_analysis
from app.services.deepseek import DeepSeekClient, DeepSeekError
from app.services.dispatch import discover_dispatch_schedules, followup_tracking_to_event
from app.services.feishu import FeishuClient, FeishuError
from app.services.fingerprint import message_fingerprint
from app.services.issues import issue_candidate_from_message, issue_schedule_match_score
from app.services.rules import load_rules_from_xlsx


app = FastAPI(title="WhatsApp Repair AI Backend", version="0.1.0")
db = Database(settings.database_path)
DOWNLOADS_DIR = Path("downloads")
AUTOMATION_NOTICE_MARKERS = ("自动化助手提示",)


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

    for message in messages:
        attachments = db.list_attachments_for_message(message["id"])
        try:
            analysis = deepseek.analyze_message(
                message=message,
                attachments=attachments,
                rules=rules,
            )
            schedules = db.list_schedules_for_message(message)
            analysis = apply_schedule_completion(
                analysis=analysis,
                message=message,
                attachments=attachments,
                schedules=schedules,
            )
            feishu_record_id = None
            if sync_feishu and settings.feishu_sync_available:
                fields = feishu.fields_for_repair_record(message, analysis, attachments)
                if feishu.enabled and message.get("feishu_record_id"):
                    feishu.update_record(message["feishu_record_id"], fields)
                    feishu_record_id = message["feishu_record_id"]
                elif feishu.enabled:
                    feishu_record_id = feishu.create_record(fields)
                else:
                    feishu_record_id = db.save_mock_feishu_record(
                        fields,
                        message.get("feishu_record_id"),
                    )
                feishu_synced += 1
            record_id = db.save_repair_record(message["id"], analysis, feishu_record_id)
            reminder_created = db.create_reminder_if_needed(record_id, analysis)
            if reminder_created:
                reminders_created += 1
            records.append(
                {
                    "message_fingerprint": message["message_fingerprint"],
                    "feishu_record_id": feishu_record_id,
                    "completion_status": analysis.get("completion_status", ""),
                    "completion_score": analysis.get("completion_score", 0),
                    "completion_level": analysis.get("completion_level", ""),
                    "reminders_created": 1 if reminder_created else 0,
                }
            )
            analyzed += 1
        except (DeepSeekError, FeishuError, ValueError) as exc:
            db.mark_message_retry(message["id"])
            failed += 1
            if first_error is None:
                first_error = str(exc)

    response: dict[str, object] = {
        "processed": len(messages),
        "analyzed": analyzed,
        "failed": failed,
        "reminders_created": reminders_created,
        "feishu_synced": feishu_synced,
        "records": records,
    }
    if first_error:
        response["first_error"] = first_error
    return response


def _analyze_pending_messages(limit: int, sync_feishu: bool) -> dict[str, object]:
    return _analyze_messages(db.list_pending_messages(limit), sync_feishu)


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
    reminder_created = db.create_reminder_if_needed(record_id, analysis)
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
    reason_items = missing_items or next_actions or [status]
    reason = "、".join(str(item) for item in reason_items if str(item).strip()) or status
    context = " ".join(item for item in [site, task_text] if item).strip()
    suffix = f"（{context}）" if context else ""
    return {
        "work_schedule_id": record.get("work_schedule_id"),
        "work_date": record.get("work_date"),
        "staff_name": staff_name,
        "site": site,
        "work_type": record.get("work_type"),
        "summary": record.get("summary") or "",
        "result": record.get("result") or "",
        "completion_status": status,
        "completion_score": record.get("completion_score", 0),
        "completion_level": record.get("completion_level", ""),
        "missing_items": missing_items,
        "next_actions": next_actions,
        "reminder_text": f"@{staff_name} 请补充/确认：{reason}{suffix}",
    }


def _run_auto_followups(work_date: str, limit: int) -> dict[str, object]:
    feishu = feishu_client()
    schedule_records = []
    existing_record_items = []
    reminders_created = 0
    feishu_synced = 0

    schedules = db.list_schedules_without_repair_records(work_date, limit)
    for schedule in schedules:
        item = _sync_schedule_gap(schedule, feishu)
        if item.get("mock_feishu_record_id"):
            feishu_synced += 1
        if item["reminder_created"]:
            reminders_created += 1
        schedule_records.append(item)

    remaining_limit = max(0, limit - len(schedules))
    repair_records = (
        db.list_repair_records_needing_followup(work_date=work_date, limit=remaining_limit)
        if remaining_limit
        else []
    )
    for record in repair_records:
        analysis = _repair_record_followup_analysis(record)
        reminder_created = db.create_reminder_if_needed(int(record["id"]), analysis)
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
    db.init()


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "database": str(settings.database_path),
        "deepseek_enabled": settings.deepseek_enabled,
        "feishu_enabled": settings.feishu_enabled,
        "feishu_mock_mode": settings.feishu_mock_mode,
        "feishu_sync_available": settings.feishu_sync_available,
    }


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


@app.post("/api/whatsapp/messages")
def ingest_whatsapp_messages(payload: WhatsAppMessageBatchIn) -> dict[str, object]:
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
    insert_result = db.insert_messages(rows)
    insert_result["filtered"] = filtered
    stored_messages = db.list_messages_by_fingerprints(fingerprints)
    dispatch_result = _discover_and_save_dispatch_schedules(stored_messages)
    return {"messages": insert_result, "dispatch_schedules": dispatch_result}


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
def whatsapp_download_jobs(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    return {"jobs": db.list_download_jobs(limit)}


@app.get("/api/whatsapp/messages/recent")
def recent_whatsapp_messages(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    return {"messages": db.list_recent_messages(limit)}


@app.get("/api/status")
def status() -> dict[str, object]:
    return {
        "health": health(),
        "counts": db.count_rows(),
    }


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
def ingest_attachment(payload: AttachmentIn) -> dict[str, object]:
    message = db.get_message_by_fingerprint(payload.message_fingerprint)
    if not message:
        raise HTTPException(status_code=404, detail="message_fingerprint not found")
    try:
        archived = archive_attachment(
            payload.temp_path,
            settings.archive_root,
            original_filename=payload.original_filename,
            work_date=payload.work_date or message["sent_at"][:10],
            site=payload.site,
            staff_name=payload.staff_name or message["sender"],
            work_type=payload.work_type,
            attachment_type=payload.attachment_type,
        )
    except FileNotFoundError as exc:
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
    return {
        "inserted": inserted,
        "archive_path": archived.archive_path,
        "sha256": archived.sha256,
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
) -> dict[str, object]:
    target_date = work_date or datetime.now().strftime("%Y-%m-%d")
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    try:
        result = _run_auto_followups(target_date, limit)
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


@app.get("/api/reminders/pending")
def pending_reminders(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    return {"reminders": db.list_pending_reminders(limit)}


@app.post("/api/reminders/result")
def reminder_result(payload: ReminderResultIn) -> dict[str, bool]:
    db.save_reminder_result(
        payload.reminder_id,
        payload.status,
        payload.result_payload,
    )
    return {"ok": True}
