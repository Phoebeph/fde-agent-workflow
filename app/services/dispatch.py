from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any

from app.services.completion import infer_work_type
from app.services.deepseek import to_simplified_text


MENTION_RE = re.compile(r"@⁨([^⁩]+)⁩")
SITE_RE = re.compile(
    r"(商场\d+|商場\d+|Landmark east|K11 Atelier|林海山城|The hari|LG2|5PP|滙丰石门|滙豐石門|告罗士打大厦|告羅士打大廈|围方|圍方|Montara|绿杨新邨|綠楊新邨|LP6|御龙山|御龍山|新屯中|又一城|Lee Garden Five|MALIBU|Elements|瑜一|扬海|揚海|海堤湾畔|海堤灣畔|君汇港|君匯港)"
)

DISPATCH_WORDS = [
    "call",
    "过去看看",
    "过去睇睇",
    "过嚟",
    "安排",
    "改去",
    "改为",
    "明早",
    "明天",
    "听日",
    "聽日",
    "麻烦",
    "麻煩",
    "帮手",
    "幫手",
    "urgent",
    "到场",
    "到場",
    "需安排",
    "抽时间",
    "抽時間",
    "可以过左去",
    "可以過左去",
    "去之前",
    "睇埋",
]

CANCEL_WORDS = ["不用去", "唔使去", "取消", "不用安排"]
FOLLOWUP_WORDS = [
    "未回复上 Group",
    "未覆返野上 Group",
    "有冇",
    "有没有",
    "咩情况",
    "咩情況",
    "仲未收到",
    "请补",
    "請補",
    "第2次问",
    "第2次問",
    "第3次问",
    "第3次問",
    "Record:",
]
MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def discover_dispatch_schedules(
    messages: list[dict[str, Any]],
    *,
    dispatch_manager_senders: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for message in messages:
        schedule = high_confidence_dispatch_to_schedule(
            message,
            dispatch_manager_senders=dispatch_manager_senders,
        )
        if schedule:
            rows.append(schedule)
    return rows


def high_confidence_dispatch_to_schedule(
    message: dict[str, Any],
    *,
    dispatch_manager_senders: tuple[str, ...],
) -> dict[str, Any] | None:
    sender = str(message.get("sender") or "").strip()
    if sender not in dispatch_manager_senders:
        return None
    raw_text = str(message.get("text") or "")
    text = to_simplified_text(raw_text)
    if not text.strip() or any(word in text for word in CANCEL_WORDS):
        return None

    mentions = _mentions(raw_text)
    sites = _sites(text)
    if not mentions or not sites or not any(word in text for word in DISPATCH_WORDS):
        return None

    assignee = _staff_name(mentions[0])
    site = sites[0]
    work_date = _work_date(str(message.get("sent_at") or ""), text)
    task_text = _task_text(text)
    if not assignee or not site or not task_text:
        return None

    return {
        "raw_message_id": message.get("id"),
        "work_date": work_date,
        "shift": None,
        "staff_name": assignee,
        "site": site,
        "task_text": task_text,
        "source_file": f"whatsapp_dispatch:{message.get('id') or message.get('message_fingerprint') or ''}",
        "ocr_confidence": 0.95,
        "review_status": "confirmed",
        "work_type": infer_work_type(task_text),
        "dispatch_sender": sender,
    }


def is_followup_tracking_message(
    message: dict[str, Any],
    *,
    followup_manager_senders: tuple[str, ...],
) -> bool:
    sender = str(message.get("sender") or "").strip()
    if sender not in followup_manager_senders:
        return False
    text = to_simplified_text(str(message.get("text") or ""))
    return any(to_simplified_text(word) in text for word in FOLLOWUP_WORDS)


def followup_tracking_to_event(
    message: dict[str, Any],
    *,
    followup_manager_senders: tuple[str, ...],
) -> dict[str, Any] | None:
    if not is_followup_tracking_message(
        message,
        followup_manager_senders=followup_manager_senders,
    ):
        return None
    raw_text = str(message.get("text") or "")
    text = to_simplified_text(raw_text)
    mentions = _mentions(raw_text)
    target_name = _staff_name(mentions[0]) if mentions else _target_from_text(text)
    work_date = _followup_work_date(text, str(message.get("sent_at") or ""))
    sites = _sites(text)
    event_type, missing_items = _followup_type_and_missing_items(text)
    return {
        "raw_message_id": message.get("id"),
        "event_type": event_type,
        "sender": str(message.get("sender") or ""),
        "target_name": target_name,
        "site": sites[0] if sites else "",
        "work_date": work_date,
        "event_text": text[:1000],
        "event_payload": {
            "missing_items": missing_items,
            "source": "followup_manager_message",
            "confidence": "high" if target_name and work_date else "medium",
        },
    }


def _mentions(text: str) -> list[str]:
    return [value.strip() for value in MENTION_RE.findall(text) if value.strip()]


def _sites(text: str) -> list[str]:
    return [to_simplified_text(value.strip()) for value in SITE_RE.findall(text) if value.strip()]


def _staff_name(value: str) -> str:
    text = to_simplified_text(value)
    for token in ["Company", "company", "ono team", "Ono team", "atl", "Atl", "~"]:
        text = text.replace(token, " ")
    return " ".join(part for part in text.split() if part).strip()


def _target_from_text(text: str) -> str:
    match = re.search(r"\b([A-Z][A-Za-z]{1,30})\s*,", text)
    return match.group(1) if match else ""


def _task_text(text: str) -> str:
    cleaned = MENTION_RE.sub("", text)
    cleaned = re.sub(r"\b\d{4}\s?\d{4}\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:500]


def _work_date(sent_at: str, text: str) -> str:
    base = _parse_sent_at(sent_at)
    if any(word in text for word in ["明早", "明天", "听日", "聽日"]):
        base += timedelta(days=1)
    return base.strftime("%Y-%m-%d")


def _parse_sent_at(value: str) -> datetime:
    stripped = value.strip()
    for fmt in [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ]:
        try:
            return datetime.strptime(stripped[: len(datetime.now().strftime(fmt))], fmt)
        except ValueError:
            continue
    return datetime.now()


def _followup_work_date(text: str, sent_at: str) -> str:
    year = _parse_sent_at(sent_at).year
    match = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", text)
    if match:
        day = int(match.group(1))
        month = MONTHS.get(match.group(2).lower(), 0)
        if month:
            return datetime(int(match.group(3)), month, day).strftime("%Y-%m-%d")
    match = re.search(r"(\d{1,2})-([A-Za-z]{3})", text)
    if match:
        day = int(match.group(1))
        month = MONTHS.get(match.group(2).lower(), 0)
        if month:
            return datetime(year, month, day).strftime("%Y-%m-%d")
    match = re.search(r"(\d{1,2})/(\d{1,2})", text)
    if match:
        return datetime(year, int(match.group(2)), int(match.group(1))).strftime("%Y-%m-%d")
    return ""


def _followup_type_and_missing_items(text: str) -> tuple[str, list[str]]:
    missing: list[str] = []
    if "未回复" in text or "未覆返" in text:
        missing.append("工作结果回复")
        return "followup_unreplied", missing
    if "维修报告" in text or "报告扫描" in text or "掃描" in text or "扫描" in text:
        missing.append("维修报告 PDF")
    if "photo record" in text.lower() or "换前" in text or "换中" in text or "换后" in text or "照片" in text:
        missing.append("照片记录")
    if "咩情况" in text or "什么情况" in text or "跟进结果" in text:
        missing.append("跟进结果")
    if not missing:
        missing.append("补充资料")
    if "维修报告 PDF" in missing:
        return "followup_missing_pdf", missing
    if "照片记录" in missing:
        return "followup_missing_photo", missing
    if "跟进结果" in missing:
        return "followup_result_needed", missing
    return "followup", missing
