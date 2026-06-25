from __future__ import annotations

import datetime
import hashlib
import json
import re
import time
import urllib.error
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

ROW_XPATH = "xpath=//div[@role='row']"
REL_CONTENT_XPATH = "xpath=.//span[contains(@class, 'selectable-text')]"
REL_META_XPATH = "xpath=.//div[contains(@class, 'copyable-text') and @data-pre-plain-text]"
REL_TODAY_DIVIDER_XPATH = "xpath=.//span[normalize-space(text())='今天' or translate(normalize-space(text()), 'today', 'TODAY')='TODAY']"
CONTAINER_SELECTOR = 'div[data-testid="conversation-panel-messages"]'


def run_daily_whatsapp_collector(page: Any) -> None:
    """Run one initial backfill after 08:00, then scan recent messages every 5 minutes."""
    did_initial_scan = False
    while True:
        now = datetime.datetime.now()
        if not did_initial_scan and now.hour >= INITIAL_SCAN_HOUR:
            messages = collect_today_backfill(page)
            post_messages(messages, scan_mode="initial_backfill")
            did_initial_scan = True
            download_pending_attachments(page)
        elif did_initial_scan:
            messages = collect_recent_messages(page, limit=INCREMENTAL_LIMIT)
            post_messages(messages, scan_mode="incremental")
            download_pending_attachments(page)
        time.sleep(SCAN_INTERVAL_SECONDS)


def collect_today_backfill(page: Any) -> list[dict[str, Any]]:
    """Scroll upward to today's divider, collecting rows on every viewport while scrolling."""
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
    """Collect recent visible messages. Backend deduplicates old messages."""
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


def download_pending_attachments(page: Any, wait_seconds: int = ATTACHMENT_JOB_WAIT_SECONDS) -> None:
    """Download analyzed attachment jobs from backend.

    The backend only exposes attachment jobs after AI analysis is done, because the site/date
    used for archiving comes from the generated repair record. Poll briefly after posting new
    messages so attachments do not get downloaded before the site is known.
    """
    jobs: list[dict[str, Any]] = []
    deadline = time.time() + wait_seconds
    while time.time() <= deadline:
        jobs = get_json(f"{BACKEND_BASE_URL}/api/whatsapp/download-jobs?limit=50").get("jobs", [])
        if jobs:
            break
        time.sleep(ATTACHMENT_JOB_POLL_SECONDS)

    print(f"附件下载任务 count={len(jobs)}")
    for job in jobs:
        downloaded_files = download_attachment_for_message(page, job)
        for file_path, attachment_type in downloaded_files:
            post_json(
                f"{BACKEND_BASE_URL}/api/whatsapp/attachments",
                {
                    "external_message_id": job.get("external_message_id"),
                    "message_fingerprint": job.get("message_fingerprint"),
                    "original_filename": Path(file_path).name,
                    "temp_path": str(file_path),
                    "attachment_type": attachment_type,
                },
            )


def download_attachment_for_message(page: Any, job: dict[str, Any]) -> list[tuple[Path, str]]:
    """Yingdao-specific adapter.

    Use job['sender'], job['sent_at'], job['text'] or job['external_message_id'] to find the WhatsApp row,
    click the image/PDF, save it to DOWNLOAD_DIR, then return [(path, attachment_type), ...].
    """
    del page, job
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return []


def post_messages(messages: list[dict[str, Any]], scan_mode: str) -> dict[str, Any]:
    if not messages:
        return {"skipped": "empty"}
    payload = {
        "group_name": GROUP_NAME,
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
    # Hong Kong WhatsApp commonly shows day/month/year. If the first number is impossible
    # as a day but possible as a month, fall back to month/day/year.
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
    raw = json.dumps(
        {
            "sender": sender,
            "sent_at": sent_at,
            "text": text,
            "attachments": attachment_hints,
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
