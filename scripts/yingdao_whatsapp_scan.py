from __future__ import annotations

import datetime
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BACKEND_BASE_URL = "http://127.0.0.1:8000"
GROUP_NAME = "test"
DOWNLOAD_DIR = Path(r"C:\Users\test\data\downloads\yingdao")
INCREMENTAL_LIMIT = 80
SCAN_INTERVAL_SECONDS = 300
INITIAL_SCAN_HOUR = 8
MAX_INITIAL_SCROLLS = 80
MAX_INCREMENTAL_SCROLLS = 4
ATTACHMENT_JOB_WAIT_SECONDS = 90
ATTACHMENT_JOB_POLL_SECONDS = 10
REMINDER_LIMIT = 50

ROW_XPATH = "xpath=//div[@role='row']"
REL_CONTENT_XPATH = "xpath=.//span[contains(@class, 'selectable-text')]"
REL_META_XPATH = "xpath=.//div[contains(@class, 'copyable-text') and @data-pre-plain-text]"
REL_TODAY_DIVIDER_XPATH = "xpath=.//span[normalize-space(text())='今天' or translate(normalize-space(text()), 'today', 'TODAY')='TODAY']"
CONTAINER_SELECTOR = 'div[data-testid="conversation-panel-messages"]'

SEARCH_BOX_SELECTORS = (
    'div[data-testid="chat-list-search"] div[contenteditable="true"]',
    'div[role="textbox"][contenteditable="true"][data-tab="3"]',
    'div[role="textbox"][contenteditable="true"]',
)
COMPOSER_SELECTORS = (
    'footer div[contenteditable="true"][data-tab]',
    'div[contenteditable="true"][data-tab="10"]',
    'div[contenteditable="true"][data-tab="6"]',
)
ROW_DOWNLOAD_XPATH = (
    "xpath=.//*[@aria-label and "
    "(contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download') "
    "or contains(@aria-label, '下载') "
    "or contains(@aria-label, '保存'))]"
)
PAGE_DOWNLOAD_XPATH = (
    "xpath=//*[@aria-label and "
    "(contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download') "
    "or contains(@aria-label, '下载') "
    "or contains(@aria-label, '保存'))]"
)
PREVIEW_CLOSE_XPATH = (
    "xpath=//*[@aria-label='Close' or @aria-label='关闭' or @aria-label='關閉']"
)

SCAN_CYCLE = "scan_cycle"
REMINDER_CYCLE = "reminder_cycle"


def run_whatsapp_automation_entry(page: Any) -> dict[str, Any]:
    """Unified Yingdao entry: claim one backend job, execute it, then exit."""
    return run_automation_once(page)


def run_automation_once(page: Any) -> dict[str, Any]:
    envelope = get_json(f"{BACKEND_BASE_URL}/api/automation/next")
    job = envelope.get("job") or {}
    if not job:
        print("自动化入口：当前无任务，直接退出")
        return {"ok": True, "status": "idle", "job": None, "config": envelope.get("config", {})}

    if not page:
        error_summary = "page is required for automation jobs"
        report_automation_job(str(job.get("run_token") or ""), "failed", {"job_type": job.get("job_type")}, error_summary)
        raise RuntimeError(error_summary)

    job_type = str(job.get("job_type") or "").strip()
    try:
        if job_type == SCAN_CYCLE:
            result = run_scan_cycle_job(page, job)
        elif job_type == REMINDER_CYCLE:
            result = run_reminder_cycle_job(page, job)
        else:
            result = {"job_status": "skipped", "reason": f"unsupported job_type: {job_type}"}

        job_status = str(result.pop("job_status", "success"))
        report_automation_job(str(job.get("run_token") or ""), job_status, result)
        return {"ok": job_status != "failed", "status": job_status, "job": job, "result": result}
    except Exception as exc:
        error_summary = str(exc)[:500]
        report_automation_job(
            str(job.get("run_token") or ""),
            "failed",
            {"job_type": job_type, "group_name": job.get("group_name")},
            error_summary,
        )
        raise


def run_scan_cycle_job(page: Any, job: dict[str, Any]) -> dict[str, Any]:
    group_name = str(job.get("group_name") or GROUP_NAME).strip() or GROUP_NAME
    ensure_group_open(page, group_name)
    messages = run_stage_1_collect_messages(page, group_name=group_name, scan_mode="scheduled_cycle")
    attachment_result = run_stage_2_download_attachments(page, group_name=group_name)
    return {
        "job_status": "success",
        "group_name": group_name,
        "messages_posted": len(messages),
        "attachments_downloaded": attachment_result.get("downloaded", 0),
        "attachments_failed": attachment_result.get("failed", 0),
        "attachments_total_jobs": attachment_result.get("total_jobs", 0),
    }


def run_reminder_cycle_job(page: Any, job: dict[str, Any]) -> dict[str, Any]:
    group_name = str(job.get("group_name") or GROUP_NAME).strip() or GROUP_NAME
    ensure_group_open(page, group_name)

    work_date = job_work_date(job)
    site_names = [str(item).strip() for item in job.get("site_names", []) if str(item).strip()]
    site_names_csv = ",".join(site_names)
    followup_url = build_url(
        f"{BACKEND_BASE_URL}/api/followups/run",
        work_date=work_date,
        limit=100,
        site_names=site_names_csv or None,
    )
    followup_result = post_json(followup_url, {})

    reminder_url = build_url(
        f"{BACKEND_BASE_URL}/api/reminders/pending",
        limit=REMINDER_LIMIT,
        site_names=site_names_csv or None,
    )
    reminders = get_json(reminder_url).get("reminders", [])

    sent = 0
    failed = 0
    skipped = 0
    for reminder in reminders:
        reminder_id = int(reminder.get("id") or 0)
        content = str(reminder.get("content") or "").strip()
        if not reminder_id or not content:
            skipped += 1
            continue
        try:
            send_text_to_current_chat(page, content)
            post_json(
                f"{BACKEND_BASE_URL}/api/reminders/result",
                {
                    "reminder_id": reminder_id,
                    "status": "sent",
                    "result_payload": {
                        "group_name": group_name,
                        "sent_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    },
                },
            )
            sent += 1
        except Exception as exc:
            failed += 1
            post_json(
                f"{BACKEND_BASE_URL}/api/reminders/result",
                {
                    "reminder_id": reminder_id,
                    "status": "failed",
                    "result_payload": {
                        "group_name": group_name,
                        "error": str(exc)[:500],
                    },
                },
            )

    return {
        "job_status": "failed" if failed else "success",
        "group_name": group_name,
        "work_date": work_date,
        "site_names": site_names,
        "followups_checked_schedules": followup_result.get("checked_schedules", 0),
        "followups_checked_repair_records": followup_result.get("checked_repair_records", 0),
        "followups_reminders_created": followup_result.get("reminders_created", 0),
        "reminders_sent": sent,
        "reminders_failed": failed,
        "reminders_skipped": skipped,
        "pending_reminders_fetched": len(reminders),
    }


def run_stage_1_collect_messages(
    page: Any,
    *,
    group_name: str | None = None,
    scan_mode: str = "scheduled_cycle",
) -> list[dict[str, Any]]:
    group_name = str(group_name or GROUP_NAME).strip() or GROUP_NAME
    messages = collect_today_backfill(page)
    post_messages(messages, scan_mode=scan_mode, group_name=group_name)
    return messages


def run_stage_2_download_attachments(
    page: Any,
    *,
    group_name: str | None = None,
    wait_seconds: int = ATTACHMENT_JOB_WAIT_SECONDS,
) -> dict[str, int]:
    return download_pending_attachments(page, wait_seconds=wait_seconds, group_name=group_name)


def run_daily_whatsapp_collector(page: Any) -> None:
    """Legacy mode: keep scanning one fixed group in-process."""
    did_initial_scan = False
    while True:
        ensure_group_open(page, GROUP_NAME)
        now = datetime.datetime.now()
        if not did_initial_scan and now.hour >= INITIAL_SCAN_HOUR:
            messages = collect_today_backfill(page)
            post_messages(messages, scan_mode="initial_backfill", group_name=GROUP_NAME)
            did_initial_scan = True
            download_pending_attachments(page, group_name=GROUP_NAME)
        elif did_initial_scan:
            messages = collect_recent_messages(page, limit=INCREMENTAL_LIMIT)
            post_messages(messages, scan_mode="incremental", group_name=GROUP_NAME)
            download_pending_attachments(page, group_name=GROUP_NAME)
        time.sleep(SCAN_INTERVAL_SECONDS)


def collect_today_backfill(page: Any) -> list[dict[str, Any]]:
    scroll_to_bottom(page)
    collected: dict[str, dict[str, Any]] = {}
    seen_previous_day = False

    for _ in range(MAX_INITIAL_SCROLLS):
        for message in extract_visible_messages(page):
            if is_today_message(message):
                collected[message["external_message_id"]] = message

        if page.locator(REL_TODAY_DIVIDER_XPATH.replace("xpath=.", "xpath=//")).count() > 0:
            scroll_messages(page, -1200)
            time.sleep(0.5)
            for message in extract_visible_messages(page):
                if is_today_message(message):
                    collected[message["external_message_id"]] = message
            break

        first_date = first_visible_message_date(page)
        if first_date and not is_today_date(first_date):
            seen_previous_day = True
            break

        scroll_messages(page, -2500)
        time.sleep(1.2)

    messages = sorted(collected.values(), key=lambda item: item.get("sent_at_sort", ""))
    print(f"初始化扫描完成，today_messages={len(messages)}, seen_previous_day={seen_previous_day}")
    return strip_internal_fields(messages)


def collect_recent_messages(page: Any, limit: int = INCREMENTAL_LIMIT) -> list[dict[str, Any]]:
    scroll_to_bottom(page)
    collected: dict[str, dict[str, Any]] = {}

    for _ in range(MAX_INCREMENTAL_SCROLLS):
        for message in extract_visible_messages(page):
            if is_today_message(message):
                collected[message["external_message_id"]] = message
        if len(collected) >= limit:
            break
        scroll_messages(page, -1000)
        time.sleep(0.5)

    messages = sorted(collected.values(), key=lambda item: item.get("sent_at_sort", ""))[-limit:]
    print(f"增量扫描完成，recent_messages={len(messages)}")
    return strip_internal_fields(messages)


def extract_visible_messages(page: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for row in page.locator(ROW_XPATH).all():
        if row.locator(REL_TODAY_DIVIDER_XPATH).count() > 0:
            continue

        meta_element = row.locator(REL_META_XPATH).first
        if meta_element.count() <= 0:
            continue

        meta_text = meta_element.get_attribute("data-pre-plain-text") or ""
        msg_date, msg_time, sender = parse_meta(meta_text)
        text = extract_message_text(row)
        attachment_hints = detect_attachment_hints(row)
        has_attachments = bool(attachment_hints)
        sent_at = normalize_whatsapp_time(msg_date, msg_time)
        external_message_id = stable_external_message_id(
            sender=sender,
            sent_at=sent_at,
            text=text,
            attachment_hints=attachment_hints,
        )

        if not text and not has_attachments:
            continue

        messages.append(
            {
                "sender": sender or "未知",
                "text": text,
                "sent_at": sent_at,
                "external_message_id": external_message_id,
                "has_attachments": has_attachments,
                "attachment_hints": attachment_hints,
                "raw_payload": {
                    "source": "yingdao",
                    "meta": meta_text,
                    "scan_time": datetime.datetime.now().isoformat(timespec="seconds"),
                },
                "sent_at_sort": sent_at,
            }
        )
    return messages


def extract_message_text(row: Any) -> str:
    parts = []
    for item in row.locator(REL_CONTENT_XPATH).all():
        text = item.inner_text().strip()
        if text:
            parts.append(text)
    return "\n".join(dict.fromkeys(parts)).strip()


def detect_attachment_hints(row: Any) -> list[dict[str, str]]:
    row_text = row.inner_text().lower()
    hints: list[dict[str, str]] = []
    if "pdf" in row_text or ".pdf" in row_text:
        hints.append({"type": "pdf", "label": "PDF"})
    if any(word in row_text for word in ["image", "photo", "照片", "相片"]):
        hints.append({"type": "image", "label": "Photo"})
    if row.locator("xpath=.//img").count() > 0 and not any(item["type"] == "image" for item in hints):
        hints.append({"type": "image", "label": "Image"})
    if row.locator("xpath=.//*[contains(@data-icon, 'document') or contains(@data-icon, 'media')]").count() > 0:
        if not hints:
            hints.append({"type": "document", "label": "Attachment"})
    return hints


def download_pending_attachments(
    page: Any,
    wait_seconds: int = ATTACHMENT_JOB_WAIT_SECONDS,
    group_name: str | None = None,
) -> dict[str, int]:
    jobs: list[dict[str, Any]] = []
    deadline = time.time() + wait_seconds
    group_name = str(group_name or "").strip()
    while time.time() <= deadline:
        url = build_url(
            f"{BACKEND_BASE_URL}/api/whatsapp/download-jobs",
            limit=50,
            group_name=group_name or None,
        )
        jobs = get_json(url).get("jobs", [])
        if jobs:
            break
        time.sleep(ATTACHMENT_JOB_POLL_SECONDS)

    print(f"附件下载任务 count={len(jobs)}, group_name={group_name or '<all>'}")
    downloaded = 0
    failed = 0
    for job in jobs:
        try:
            downloaded_files = download_attachment_for_message(page, job)
            if not downloaded_files:
                failed += 1
                continue
            for file_path, attachment_type in downloaded_files:
                post_json(
                    f"{BACKEND_BASE_URL}/api/whatsapp/attachments",
                    {
                        "external_message_id": job.get("external_message_id"),
                        "message_fingerprint": job.get("message_fingerprint"),
                        "original_filename": Path(file_path).name,
                        "temp_path": str(file_path),
                        "attachment_type": attachment_type,
                        "site": job.get("site"),
                        "staff_name": job.get("staff_name"),
                        "work_type": job.get("work_type"),
                        "work_date": job.get("work_date"),
                    },
                )
                downloaded += 1
        except Exception as exc:
            failed += 1
            print(f"附件下载失败: external_message_id={job.get('external_message_id')} error={exc}")
    return {"total_jobs": len(jobs), "downloaded": downloaded, "failed": failed}


def download_attachment_for_message(page: Any, job: dict[str, Any]) -> list[tuple[Path, str]]:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    row = find_message_row(page, job)
    if row is None:
        raise RuntimeError(f"message row not found: {job.get('external_message_id') or job.get('message_fingerprint')}")

    results: list[tuple[Path, str]] = []
    expected_types = [
        str(item).strip().lower()
        for item in job.get("missing_attachment_types", []) or []
        if str(item).strip()
    ]
    if not expected_types:
        expected_types = [
            str(item.get("type") or "").strip().lower()
            for item in job.get("attachment_hints", []) or []
            if isinstance(item, dict) and str(item.get("type") or "").strip()
        ]
    if not expected_types:
        expected_types = ["document"]

    for expected_type in expected_types:
        file_path = try_download_attachment_type(page, row, expected_type)
        if file_path:
            results.append((file_path, normalize_attachment_type(expected_type, file_path)))
            continue
        if expected_type == "image" and row.locator("xpath=.//img").count() > 0:
            screenshot_path = DOWNLOAD_DIR / f"snap_{job.get('external_message_id') or job.get('message_fingerprint')}_{len(results) + 1}.png"
            row.screenshot(path=str(screenshot_path))
            results.append((screenshot_path, "image"))
    return results


def try_download_attachment_type(page: Any, row: Any, expected_type: str) -> Path | None:
    before = snapshot_downloads()

    row_download = row.locator(ROW_DOWNLOAD_XPATH).first
    if row_download.count() > 0:
        downloaded = download_from_locator(row_download, before, expected_type)
        if downloaded:
            return downloaded

    if expected_type in {"pdf", "document", "video", "other"}:
        preview_trigger = first_existing_locator(
            row,
            (
                "xpath=.//*[contains(@data-icon, 'document')]",
                "xpath=.//*[contains(translate(text(), 'PDF', 'pdf'), 'pdf')]",
                "xpath=.//*[@role='button']",
            ),
        )
    else:
        preview_trigger = first_existing_locator(
            row,
            (
                "xpath=.//img",
                "xpath=.//*[@role='button'][.//img]",
                "xpath=.//*[@role='button']",
            ),
        )

    if preview_trigger is None:
        return newest_download_since(before, expected_type)

    try:
        preview_trigger.click()
        time.sleep(1)
    except Exception:
        pass

    page_download = page.locator(PAGE_DOWNLOAD_XPATH).first
    if page_download.count() > 0:
        downloaded = download_from_locator(page_download, before, expected_type)
        close_preview_if_open(page)
        if downloaded:
            return downloaded

    close_preview_if_open(page)
    return newest_download_since(before, expected_type)


def find_message_row(page: Any, job: dict[str, Any]) -> Any | None:
    target_external_id = str(job.get("external_message_id") or "").strip()
    target_sender = str(job.get("sender") or "").strip()
    target_text = normalize_text_for_match(str(job.get("text") or ""))
    target_sent_at = str(job.get("sent_at") or "").strip()

    candidates = page.locator(ROW_XPATH).all()
    for row in reversed(candidates):
        meta_element = row.locator(REL_META_XPATH).first
        if meta_element.count() <= 0:
            continue
        meta_text = meta_element.get_attribute("data-pre-plain-text") or ""
        msg_date, msg_time, sender = parse_meta(meta_text)
        text = extract_message_text(row)
        sent_at = normalize_whatsapp_time(msg_date, msg_time)
        current_external_id = stable_external_message_id(
            sender=sender,
            sent_at=sent_at,
            text=text,
            attachment_hints=[],
        )
        if target_external_id and current_external_id == target_external_id:
            return row
        if target_sender and sender != target_sender:
            continue
        if target_sent_at and sent_at != target_sent_at:
            continue
        if target_text and normalize_text_for_match(text) != target_text:
            continue
        return row
    return None


def ensure_group_open(page: Any, group_name: str) -> bool:
    group_name = str(group_name or "").strip()
    if not group_name:
        return False
    if current_chat_title(page).casefold() == group_name.casefold():
        return True

    search_box = first_existing_locator(page, SEARCH_BOX_SELECTORS)
    if search_box is None:
        raise RuntimeError("WhatsApp search box not found")

    search_box.click()
    time.sleep(0.3)
    clear_editable_locator(search_box)
    search_box.fill(group_name)
    time.sleep(1)

    chat_locator = page.locator(
        f"xpath=//span[@title={json.dumps(group_name)}] | //div[@title={json.dumps(group_name)}]"
    ).first
    if chat_locator.count() <= 0:
        raise RuntimeError(f"WhatsApp group not found in chat list: {group_name}")
    chat_locator.click()
    time.sleep(1.5)
    scroll_to_bottom(page)
    return True


def current_chat_title(page: Any) -> str:
    locator = page.locator("xpath=(//header//span[@title])[1] | (//header//div[@title])[1]").first
    if locator.count() <= 0:
        return ""
    return (locator.get_attribute("title") or locator.inner_text() or "").strip()


def send_text_to_current_chat(page: Any, content: str) -> None:
    composer = first_existing_locator(page, COMPOSER_SELECTORS)
    if composer is None:
        raise RuntimeError("WhatsApp message composer not found")
    composer.click()
    time.sleep(0.2)
    clear_editable_locator(composer)
    composer.fill(content)
    time.sleep(0.2)
    composer.press("Enter")
    time.sleep(0.8)


def clear_editable_locator(locator: Any) -> None:
    try:
        locator.press("Control+A")
        locator.press("Backspace")
        return
    except Exception:
        pass
    try:
        locator.fill("")
    except Exception:
        pass


def first_existing_locator(root: Any, selectors: tuple[str, ...]) -> Any | None:
    for selector in selectors:
        locator = root.locator(selector).first
        try:
            if locator.count() > 0:
                return locator
        except Exception:
            continue
    return None


def close_preview_if_open(page: Any) -> None:
    close_button = page.locator(PREVIEW_CLOSE_XPATH).first
    if close_button.count() > 0:
        try:
            close_button.click()
            time.sleep(0.5)
            return
        except Exception:
            pass
    keyboard = getattr(page, "keyboard", None)
    if keyboard is not None:
        try:
            keyboard.press("Escape")
            time.sleep(0.5)
        except Exception:
            pass


def snapshot_downloads() -> dict[str, int]:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    snapshot: dict[str, int] = {}
    for path in DOWNLOAD_DIR.rglob("*"):
        if not path.is_file():
            continue
        try:
            snapshot[str(path)] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return snapshot


def newest_download_since(before: dict[str, int], expected_type: str) -> Path | None:
    candidates: list[Path] = []
    for path in DOWNLOAD_DIR.rglob("*"):
        if not path.is_file():
            continue
        previous = before.get(str(path))
        try:
            current_mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
        if previous is None or current_mtime > previous:
            normalized_type = normalize_attachment_type(expected_type, path)
            if expected_type in {"document", "other"} or normalized_type == expected_type:
                candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.stat().st_mtime, str(item)), reverse=True)
    return candidates[0]


def download_from_locator(locator: Any, before: dict[str, int], expected_type: str) -> Path | None:
    try:
        downloaded_path = locator.download(str(DOWNLOAD_DIR), timeout=15000)
        if downloaded_path:
            path = Path(str(downloaded_path))
            if path.exists():
                return path
    except Exception:
        pass
    time.sleep(1)
    return newest_download_since(before, expected_type)


def normalize_attachment_type(expected_type: str, file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif"}:
        return "image"
    if suffix in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}:
        return "video"
    if expected_type in {"image", "pdf", "video", "document", "other"}:
        return expected_type
    return "document"


def report_automation_job(
    run_token: str,
    status: str,
    result_payload: dict[str, Any],
    error_summary: str = "",
) -> None:
    if not run_token:
        return
    try:
        post_json(
            f"{BACKEND_BASE_URL}/api/automation/report",
            {
                "run_token": run_token,
                "status": status,
                "error_summary": error_summary,
                "result_payload": result_payload,
            },
        )
    except Exception as exc:
        print(f"自动化结果回报失败 run_token={run_token} error={exc}")


def job_work_date(job: dict[str, Any]) -> str:
    scheduled_for = str(job.get("scheduled_for") or "").strip()
    if scheduled_for:
        try:
            return datetime.datetime.fromisoformat(scheduled_for).date().isoformat()
        except ValueError:
            pass
    return datetime.datetime.now().date().isoformat()


def build_url(url: str, **params: object) -> str:
    filtered = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }
    if not filtered:
        return url
    return f"{url}?{urllib.parse.urlencode(filtered)}"


def post_messages(messages: list[dict[str, Any]], scan_mode: str, group_name: str | None = None) -> dict[str, Any]:
    if not messages:
        return {"skipped": "empty"}
    payload = {
        "group_name": group_name or GROUP_NAME,
        "messages": messages,
        "raw_payload": {
            "source": "yingdao",
            "scan_mode": scan_mode,
            "scan_time": datetime.datetime.now().isoformat(timespec="seconds"),
        },
    }
    result = post_json(f"{BACKEND_BASE_URL}/api/whatsapp/messages", payload)
    print(
        "已提交后端 "
        f"group_name={payload['group_name']}, "
        f"scan_mode={scan_mode}, messages={len(messages)}, "
        f"result={result.get('messages')}, auto_pipeline={result.get('auto_pipeline')}"
    )
    return result


def parse_meta(meta_text: str) -> tuple[str, str, str]:
    try:
        if not meta_text or "]" not in meta_text:
            return "", "", ""
        time_date_part = meta_text.split("]")[0].strip("[")
        sender = meta_text.split("]")[1].strip().rstrip(":")
        parts = [part.strip() for part in time_date_part.split(",")]
        msg_time = parts[0] if parts else ""
        msg_date = parts[1] if len(parts) > 1 else ""
        return msg_date, msg_time, sender
    except Exception:
        return "", "", "未知"


def normalize_whatsapp_time(msg_date: str, msg_time: str) -> str:
    today = datetime.datetime.now()
    date_text = msg_date.strip() or f"{today.day}/{today.month}/{today.year}"
    if date_text in {"今天", "TODAY", "Today"}:
        date_text = f"{today.day}/{today.month}/{today.year}"
    parsed = parse_whatsapp_datetime(date_text, msg_time)
    if parsed:
        return parsed.replace(
            tzinfo=datetime.timezone(datetime.timedelta(hours=8))
        ).isoformat(timespec="seconds")
    return f"{date_text} {msg_time}".strip()


def parse_whatsapp_datetime(msg_date: str, msg_time: str) -> datetime.datetime | None:
    date_match = re.search(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<year>\d{4})", msg_date)
    time_match = re.search(r"(?P<period>上午|下午|AM|PM|am|pm)?\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})", msg_time)
    if not date_match or not time_match:
        return None

    first = int(date_match.group("a"))
    second = int(date_match.group("b"))
    year = int(date_match.group("year"))
    day = first
    month = second
    if first <= 12 and second > 12:
        month = first
        day = second

    hour = int(time_match.group("hour"))
    minute = int(time_match.group("minute"))
    period = time_match.group("period")
    if period in {"下午", "PM", "pm"} and hour < 12:
        hour += 12
    elif period in {"上午", "AM", "am"} and hour == 12:
        hour = 0
    try:
        return datetime.datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def is_today_message(message: dict[str, Any]) -> bool:
    sent_at = str(message.get("时间") or message.get("sent_at_sort") or "")
    return is_today_date(sent_at)


def is_today_date(value: str) -> bool:
    now = datetime.datetime.now()
    targets = {
        now.strftime("%Y-%m-%d"),
        f"{now.day}/{now.month}/{now.year}",
        now.strftime("%d/%m/%Y"),
        f"{now.month}/{now.day}/{now.year}",
        "今天",
        "Today",
        "TODAY",
    }
    return any(target in value for target in targets)


def first_visible_message_date(page: Any) -> str:
    first_row = page.locator(ROW_XPATH).first
    if first_row.count() <= 0:
        return ""
    meta = first_row.locator(REL_META_XPATH).first
    if meta.count() <= 0:
        return ""
    msg_date, _, _ = parse_meta(meta.get_attribute("data-pre-plain-text") or "")
    return msg_date


def stable_external_message_id(
    *,
    sender: str,
    sent_at: str,
    text: str,
    attachment_hints: list[dict[str, str]],
) -> str:
    del attachment_hints
    raw = json.dumps(
        {
            "sender": sender,
            "sent_at": sent_at,
            "text": text,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "yingdao_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def strip_internal_fields(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for message in messages:
        item = dict(message)
        item.pop("sent_at_sort", None)
        result.append(item)
    return result


def normalize_text_for_match(value: str) -> str:
    return "\n".join(line.strip() for line in str(value or "").splitlines() if line.strip()).strip()


def scroll_to_bottom(page: Any) -> None:
    page.evaluate(f"document.querySelector('{CONTAINER_SELECTOR}')?.scrollBy(0, 999999)")
    time.sleep(1)


def scroll_messages(page: Any, delta_y: int) -> None:
    page.evaluate(f"document.querySelector('{CONTAINER_SELECTOR}')?.scrollBy(0, {delta_y})")


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"HTTP error {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}")
        return {}

