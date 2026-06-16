from __future__ import annotations

from typing import Any

from app.services.deepseek import to_simplified_text
from app.services.dispatch import SITE_RE


ISSUE_WORDS = [
    "坏",
    "故障",
    "问题",
    "无反应",
    "异常",
    "不停闪",
    "又闪",
    "又坏",
    "客户说",
    "客人话",
    "需要处理",
    "要解决",
    "不能用",
]
COMPLETION_WORDS = [
    "完成",
    "已完成",
    "测试正常",
    "恢复正常",
    "已处理",
    "已修复",
    "已更换",
    "离场",
]
MATCH_TOKENS = [
    "CCTV",
    "mon",
    "NVR",
    "门磁",
    "门锁",
    "电锁",
    "读卡",
    "车闸",
    "线路",
    "弱电",
    "火牛",
    "控制器",
    "显示器",
    "闪",
    "无反应",
    "故障",
]


def issue_candidate_from_message(
    message: dict[str, Any],
    *,
    dispatch_manager_senders: tuple[str, ...],
    followup_manager_senders: tuple[str, ...],
) -> dict[str, Any] | None:
    sender = str(message.get("sender") or "").strip()
    if sender in dispatch_manager_senders or sender in followup_manager_senders:
        return None

    text = to_simplified_text(str(message.get("text") or "")).strip()
    if not text or _looks_like_completion(text):
        return None
    if not any(word in text for word in ISSUE_WORDS):
        return None

    sites = _sites(text)
    confidence = 0.65
    if sites:
        confidence += 0.2
    if any(word in text for word in ["客户说", "需要处理", "要解决"]):
        confidence += 0.1
    confidence = min(0.95, confidence)

    return {
        "raw_message_id": message.get("id"),
        "reported_by": sender,
        "work_date": str(message.get("sent_at") or "")[:10],
        "site": sites[0] if sites else "",
        "issue_text": text[:1000],
        "issue_summary": _summary(text),
        "confidence": confidence,
    }


def _looks_like_completion(text: str) -> bool:
    return any(word in text for word in COMPLETION_WORDS)


def _sites(text: str) -> list[str]:
    return [to_simplified_text(value.strip()) for value in SITE_RE.findall(text) if value.strip()]


def _summary(text: str) -> str:
    return text[:240]


def issue_schedule_match_score(issue: dict[str, Any], schedule: dict[str, Any]) -> int:
    issue_site = to_simplified_text(str(issue.get("site") or ""))
    schedule_site = to_simplified_text(str(schedule.get("site") or ""))
    if issue_site and schedule_site and issue_site != schedule_site:
        return 0

    issue_text = to_simplified_text(
        " ".join(
            str(issue.get(key) or "")
            for key in ["issue_text", "issue_summary"]
        )
    )
    schedule_text = to_simplified_text(str(schedule.get("task_text") or ""))
    score = 5 if issue_site and schedule_site and issue_site == schedule_site else 0
    for token in MATCH_TOKENS:
        if token in issue_text and token in schedule_text:
            score += 2
    return score
