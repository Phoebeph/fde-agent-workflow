from __future__ import annotations

from typing import Any

from app.services.deepseek import to_simplified_text
from app.services.scoring import apply_completion_score


FOLLOW_UP_WORDS = ["待", "未", "后补", "稍后", "下次", "跟进", "报价", "确认", "未完成"]
FAULT_WORDS = ["坏", "故障", "问题", "维修", "更换", "修复", "无反应", "异常"]
QUOTE_WORDS = ["报价", "放线", "路线", "平面图", "工程图"]
DELIVERY_WORDS = ["送货", "交货", "签收"]
INSPECTION_WORDS = ["例检", "检查", "测试"]


def apply_schedule_completion(
    *,
    analysis: dict[str, Any],
    message: dict[str, Any],
    attachments: list[dict[str, Any]],
    schedules: list[dict[str, Any]],
) -> dict[str, Any]:
    result = dict(analysis)
    matched = match_schedule(message, schedules)
    if not matched:
        result["schedule_match_status"] = "未匹配计划任务" if schedules else "无计划任务上下文"
        return result

    schedule_text = _schedule_text(matched)
    message_text = to_simplified_text(str(message.get("text") or ""))
    missing_items = list(result.get("missing_items") or [])
    next_actions = list(result.get("next_actions") or [])

    required_items = required_evidence(schedule_text, message_text)
    missing_items.extend(missing_required_items(required_items, message, attachments))

    if not has_clear_result(message_text):
        next_actions.append("补充明确工作结果")
    if any(word in message_text for word in FOLLOW_UP_WORDS):
        next_actions.append("需要继续安排跟进")

    result["work_schedule_id"] = matched.get("id")
    result["matched_schedule"] = {
        "work_date": matched.get("work_date"),
        "staff_name": matched.get("staff_name"),
        "site": matched.get("site"),
        "task_text": matched.get("task_text"),
    }
    result["schedule_match_status"] = "已匹配计划任务"
    result["site"] = to_simplified_text(str(result.get("site") or matched.get("site") or ""))
    result["staff_name"] = to_simplified_text(str(result.get("staff_name") or matched.get("staff_name") or ""))
    result["work_date"] = str(result.get("work_date") or matched.get("work_date") or message.get("sent_at", "")[:10])
    result["summary"] = to_simplified_text(str(result.get("summary") or message_text[:240]))
    result["missing_items"] = _filter_items_with_evidence(
        _dedupe([to_simplified_text(item) for item in missing_items]),
        message_text,
        attachments,
    )
    result["next_actions"] = _filter_items_with_evidence(
        _dedupe([to_simplified_text(item) for item in next_actions]),
        message_text,
        attachments,
    )

    if not message_text.strip():
        result["completion_status"] = "未回复"
    elif _needs_work_followup(message_text, result["next_actions"]):
        result["completion_status"] = "需要跟进"
    elif result["missing_items"]:
        result["completion_status"] = "资料不足"
    elif result["next_actions"]:
        result["completion_status"] = "需要跟进"
    else:
        result["completion_status"] = "已完成"

    if result["completion_status"] != "已完成":
        reason = "、".join(result["missing_items"] or result["next_actions"] or [result["completion_status"]])
        result["reminder_text"] = f"@{result['staff_name'] or '相关同事'} 请补充/确认：{reason}"
    return apply_completion_score(result)


def match_schedule(message: dict[str, Any], schedules: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not schedules:
        return None
    text = to_simplified_text(str(message.get("text") or ""))
    sender = to_simplified_text(str(message.get("sender") or "")).lower()
    best: tuple[int, dict[str, Any]] | None = None
    for schedule in schedules:
        score = 0
        staff = to_simplified_text(str(schedule.get("staff_name") or "")).lower()
        site = to_simplified_text(str(schedule.get("site") or ""))
        task_text = to_simplified_text(str(schedule.get("task_text") or ""))
        if staff and (staff == sender or staff in sender or sender in staff):
            score += 5
        if site and site in text:
            score += 4
        for keyword in _keywords(task_text):
            if keyword in text:
                score += 1
        if score > 0 and (best is None or score > best[0]):
            best = (score, schedule)
    return best[1] if best else None


def required_evidence(schedule_text: str, message_text: str) -> list[str]:
    combined = f"{schedule_text}\n{message_text}"
    required = ["工作结果回复"]
    if any(word in combined for word in FAULT_WORDS):
        required.extend(["照片记录", "维修报告 PDF"])
    if any(word in combined for word in QUOTE_WORDS):
        required.append("路线图或平面图")
    if any(word in combined for word in DELIVERY_WORDS):
        required.append("送货照片")
    return _dedupe(required)


def missing_required_items(
    required_items: list[str],
    message: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> list[str]:
    text = to_simplified_text(str(message.get("text") or ""))
    attachment_types = {str(item.get("attachment_type") or "") for item in attachments}
    image_count = sum(1 for item in attachments if str(item.get("attachment_type") or "") == "image")
    hints = message.get("attachment_hints") or []
    hint_labels = " ".join(
        to_simplified_text(str(item.get("label") or item.get("role") or item.get("type") or ""))
        for item in hints
        if isinstance(item, dict)
    )
    missing: list[str] = []
    for item in required_items:
        if item == "工作结果回复" and not has_clear_result(text):
            missing.append("明确工作结果")
        elif item == "照片记录" and "image" not in attachment_types:
            missing.append("照片记录")
        elif item == "维修报告 PDF" and "pdf" not in attachment_types:
            missing.append("维修报告 PDF")
        elif item == "路线图或平面图" and not _has_route_evidence(attachment_types, hint_labels, text):
            missing.append("路线图或平面图")
        elif item == "送货照片" and "image" not in attachment_types:
            missing.append("送货照片")
    return missing


def has_clear_result(text: str) -> bool:
    if not text.strip():
        return False
    result_words = ["完成", "正常", "已修复", "已更换", "已送货", "已处理", "恢复正常", "测试正常"]
    return any(word in text for word in result_words)


def _needs_work_followup(message_text: str, next_actions: list[str]) -> bool:
    del next_actions
    combined = message_text
    followup_words = ["未完成", "继续安排", "需要继续", "报价", "待客户", "待主管", "等主管", "再处理", "下次"]
    return any(word in combined for word in followup_words)


def schedule_gap_analysis(schedule: dict[str, Any]) -> dict[str, Any]:
    staff = to_simplified_text(str(schedule.get("staff_name") or "相关同事"))
    site = to_simplified_text(str(schedule.get("site") or ""))
    task_text = to_simplified_text(str(schedule.get("task_text") or ""))
    reason = f"{site} {task_text}".strip()
    analysis = {
        "work_schedule_id": schedule.get("id"),
        "work_date": schedule.get("work_date"),
        "staff_name": staff,
        "site": site,
        "work_type": infer_work_type(task_text),
        "summary": f"计划任务未见 WhatsApp 完成回复：{reason}",
        "result": "",
        "completion_status": "未回复",
        "missing_items": ["工作结果回复"],
        "next_actions": ["提醒同事补充当天工作结果"],
        "reminder_text": f"@{staff} 今天有计划任务未见完成回复，请补充工作结果：{reason}",
        "matched_schedule": {
            "work_date": schedule.get("work_date"),
            "staff_name": staff,
            "site": site,
            "task_text": task_text,
        },
        "schedule_match_status": "计划任务未回复",
    }
    return apply_completion_score(analysis)


def infer_work_type(text: str) -> str:
    simplified = to_simplified_text(text)
    if any(word in simplified for word in DELIVERY_WORDS):
        return "delivery"
    if any(word in simplified for word in QUOTE_WORDS):
        return "quotation"
    if any(word in simplified for word in FAULT_WORDS):
        return "maintenance"
    if any(word in simplified for word in INSPECTION_WORDS):
        return "例检"
    return "other"


def _schedule_text(schedule: dict[str, Any]) -> str:
    return to_simplified_text(
        "\n".join(
            str(schedule.get(key) or "")
            for key in ["work_date", "shift", "staff_name", "site", "task_text"]
        )
    )


def _keywords(text: str) -> list[str]:
    simplified = to_simplified_text(text)
    words = []
    for token in INSPECTION_WORDS + FAULT_WORDS + QUOTE_WORDS + DELIVERY_WORDS:
        if token in simplified:
            words.append(token)
    return _dedupe(words)


def _has_route_evidence(attachment_types: set[str], hint_labels: str, text: str) -> bool:
    if "路线" in hint_labels or "平面图" in hint_labels or "route" in hint_labels.lower():
        return True
    if "路线图已上传" in text or "平面图已上传" in text:
        return bool(attachment_types)
    return False


def _filter_items_with_evidence(
    items: list[str],
    message_text: str,
    attachments: list[dict[str, Any]],
) -> list[str]:
    attachment_types = {str(item.get("attachment_type") or "") for item in attachments}
    image_count = sum(1 for item in attachments if str(item.get("attachment_type") or "") == "image")
    has_any_attachment = bool(attachment_types)
    result_is_clear = has_clear_result(message_text)
    filtered = []
    for item in items:
        normalized = to_simplified_text(str(item))
        compact = normalized.replace(" ", "")
        if "ELVGroup" in compact:
            continue
        if result_is_clear and any(word in compact for word in ["工作结果", "汇报"]):
            continue
        if "pdf" in {value.lower() for value in attachment_types} and any(
            word in compact for word in ["维修报告", "PDF", "报告是否已签"]
        ):
            continue
        if "image" in attachment_types and (
            compact in {"照片记录", "无照片记录", "附件", "附件未上传"}
            or "无照片" in compact
        ):
            continue
        if image_count >= 3 and any(word in compact for word in ["换前", "换中", "换后"]):
            continue
        if has_any_attachment and compact in {"附件", "附件未上传"}:
            continue
        filtered.append(normalized)
    return _dedupe(filtered)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if value and value not in result:
            result.append(value)
    return result
