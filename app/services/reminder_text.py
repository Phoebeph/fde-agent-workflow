from __future__ import annotations

from typing import Any
from datetime import datetime


QUESTION_TEMPLATES = {
    "work_result": "咩情況? 有冇工作結果?",
    "inspection_result": "咩情況? 有冇檢查結果?",
    "replacement_result": "咩情況? 有冇更換結果?",
    "repair_report_pdf": "有冇維修報告掃描?",
    "photo_record": "有冇 換前 換中 換後 的 Photo Record?",
    "quotation_photo_reference": "有冇 Photo Record / 相片參考?",
    "route_plan": "有冇放線路線平面圖?",
    "delivery_photo": "有冇送貨相? 一張 wide shot 影到物料同放置位置，一張 close up 影到物料型號同 packing?",
}

DEFAULT_QUESTION = "咩情況? 有冇最新跟進結果?"

ROUTE_PLAN_NOTE = (
    "如要報價放新線，要在平面圖 mark 返條路線，唔一定要工程圖，"
    "走火通道平面圖都可以，目的係要顯示返放線路線俾客，冇附上平面圖，是出唔到報價的。"
)


def generate_reminder_message(task: dict[str, Any]) -> str:
    mention_name = _text(task.get("mention_name"))
    assignee = _text(task.get("assignee"))
    reminder_count = _reminder_count(task.get("reminder_count"))
    task_date = _text(task.get("task_date"))
    site = _text(task.get("site"))
    task_content = _text(task.get("task_content"))
    missing_type = _text(task.get("missing_type")).lower()
    record = _text(task.get("record"))

    question = QUESTION_TEMPLATES.get(missing_type, DEFAULT_QUESTION)
    if missing_type == "route_plan":
        question = f"{question}\n\n{ROUTE_PLAN_NOTE}"

    lines = [
        f"{mention_name} {assignee}，仲未收到你回覆（第{reminder_count}次问）".strip(),
        "",
        f"{assignee}，{task_date}，{site}，\"{task_content}\"",
        "",
        question,
    ]
    if record:
        lines.extend(["", "Record:", f"\"{record}\""])
    return "\n".join(lines)


def reminder_missing_type(analysis: dict[str, Any]) -> str:
    text = " ".join(
        str(item)
        for item in [
            analysis.get("completion_status", ""),
            analysis.get("summary", ""),
            analysis.get("result", ""),
            analysis.get("work_type", ""),
            *(analysis.get("missing_items") or []),
            *(analysis.get("next_actions") or []),
        ]
    )
    lower = text.lower()
    compact = text.replace(" ", "")

    if any(word in compact for word in ["路线图", "路線圖", "平面图", "平面圖", "放线", "放線", "走线", "走線"]):
        return "route_plan"
    if "送货" in compact or "送貨" in compact or "delivery" in lower:
        return "delivery_photo"
    if "维修报告" in compact or "維修報告" in compact or "pdf" in lower or "扫描" in compact or "掃描" in compact:
        return "repair_report_pdf"
    if any(word in compact for word in ["换前", "换中", "换后", "更换前", "更换中", "更换后"]):
        return "photo_record"
    if ("报价" in compact or "報價" in compact) and any(word in lower for word in ["photo", "照片", "相片"]):
        return "quotation_photo_reference"
    if any(word in lower for word in ["photo", "照片", "相片", "logbook"]):
        return "photo_record"
    if "检查" in compact or "檢查" in compact or "例检" in compact or "例檢" in compact:
        return "inspection_result"
    if "更换" in compact or "更換" in compact:
        return "replacement_result"
    if any(word in compact for word in ["工作结果", "工作結果", "未回复", "未回覆"]):
        return "work_result"
    return "unknown"


def generate_analysis_reminder_message(
    analysis: dict[str, Any],
    *,
    record: str = "",
    reminder_count: int = 1,
) -> str:
    staff_name = _text(analysis.get("staff_name")) or "相关同事"
    mention_name = _text(analysis.get("mention_name")) or _mention(staff_name)
    matched = analysis.get("matched_schedule") if isinstance(analysis.get("matched_schedule"), dict) else {}
    task_content = (
        _text(matched.get("task_text"))
        or _text(analysis.get("task_text"))
        or _text(analysis.get("summary"))
        or _text(analysis.get("result"))
    )
    task = {
        "mention_name": mention_name,
        "assignee": staff_name,
        "reminder_count": reminder_count,
        "task_date": _format_task_date(_text(analysis.get("work_date")) or _text(matched.get("work_date"))),
        "site": _text(analysis.get("site")) or _text(matched.get("site")),
        "task_content": task_content,
        "missing_type": reminder_missing_type(analysis),
        "record": record,
    }
    return generate_reminder_message(task)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _reminder_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 1
    return count if count > 0 else 1


def _mention(staff_name: str) -> str:
    if not staff_name:
        return ""
    return staff_name if staff_name.startswith("@") else f"@{staff_name}"


def _format_task_date(value: str) -> str:
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value[:10] if fmt == "%Y-%m-%d" else value, fmt).strftime("%d-%b")
        except ValueError:
            continue
    return value
