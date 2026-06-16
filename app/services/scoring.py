from __future__ import annotations

from typing import Any


SEVERE_ACTION_WORDS = ["未完成", "报价", "待客户", "待主管", "下次"]


def apply_completion_score(analysis: dict[str, Any]) -> dict[str, Any]:
    result = dict(analysis)
    status = str(result.get("completion_status") or "待人工确认")
    missing_items = [str(item) for item in result.get("missing_items", []) or []]
    next_actions = [str(item) for item in result.get("next_actions", []) or []]
    summary_text = " ".join(
        str(result.get(key) or "")
        for key in ["summary", "result", "reminder_text"]
    )
    action_text = " ".join(next_actions)

    if status in {"未回复", "未回覆"}:
        score = 0
    elif status == "已完成":
        score = 100
    elif status in {"资料不足", "資料不足"}:
        score = 96
    elif status in {"需要跟进", "需要跟進"}:
        score = 45
    else:
        score = 50

    if _contains_any(summary_text + " " + action_text, SEVERE_ACTION_WORDS):
        score = min(score, 45)

    for item in missing_items:
        score -= _missing_penalty(item)

    if next_actions and status not in {"未回复", "未回覆"}:
        score -= min(12, 3 * len(next_actions))

    score = max(0, min(100, int(score)))
    result["completion_score"] = score
    result["completion_level"] = completion_level(score)
    return result


def completion_level(score: int) -> str:
    if score >= 85:
        return "高"
    if score >= 70:
        return "较高"
    if score >= 50:
        return "中"
    if score >= 30:
        return "较低"
    return "低"


def _missing_penalty(item: str) -> int:
    normalized = item.replace(" ", "")
    if "明确工作结果" in normalized or "工作结果" in normalized:
        return 35
    if "换前" in normalized or "换中" in normalized or "换后" in normalized:
        return 8
    if "维修报告" in normalized or "PDF" in normalized:
        return 15
    if "照片记录" in normalized or "附件未上传" in normalized:
        return 15
    if "路线图" in normalized or "平面图" in normalized:
        return 12
    if "物料来源" in normalized:
        return 6
    if "送货照片" in normalized:
        return 12
    return 8


def _contains_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)
