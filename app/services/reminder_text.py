from __future__ import annotations

from typing import Any


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
