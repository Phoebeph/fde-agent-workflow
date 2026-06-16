from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.services.scoring import apply_completion_score


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def analyze_message(
        self,
        *,
        message: dict[str, Any],
        attachments: list[dict[str, Any]],
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self.enabled:
            return rule_based_analysis(message, attachments, rules)

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You convert Hong Kong maintenance WhatsApp messages into strict JSON. "
                        "Return only one JSON object. Do not include markdown. "
                        "Use Simplified Chinese labels where status text is needed."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "attachments": [
                                {
                                    "type": item.get("attachment_type"),
                                    "filename": item.get("original_filename"),
                                }
                                for item in attachments
                            ],
                            "rules": rules[:30],
                            "required_json_schema": {
                                "work_date": "YYYY-MM-DD or empty string",
                                "staff_name": "sender/staff name",
                                "site": "site/location if known",
                                "work_type": "例检/ad-hoc/maintenance/delivery/quotation/other",
                                "summary": "short maintenance summary",
                                "result": "work result",
                                "completion_status": "已完成|资料不足|需要跟进|待人工确认|未回复",
                                "completion_score": "0-100 integer, higher means more complete",
                                "completion_level": "高|较高|中|较低|低",
                                "missing_items": ["missing photo/pdf/report/detail if any"],
                                "next_actions": ["follow-up action if any"],
                                "reminder_text": "WhatsApp reminder text if missing_items or follow-up is needed",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        data = self._post_json("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DeepSeekError("DeepSeek returned an invalid analysis payload") from exc
        return normalize_analysis(result, message, attachments, rules)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise DeepSeekError(f"DeepSeek HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise DeepSeekError(f"DeepSeek request failed: {exc.reason}") from exc


def rule_based_analysis(
    message: dict[str, Any],
    attachments: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    text = (message.get("text") or "").strip()
    lower = text.lower()
    attachment_types = {item.get("attachment_type") for item in attachments}
    missing_items: list[str] = []
    next_actions: list[str] = []

    work_type = "other"
    if "例檢" in text or "例检" in text:
        work_type = "例检"
    elif "送貨" in text or "送货" in text:
        work_type = "delivery"
    elif "報價" in text or "报价" in text:
        work_type = "quotation"
    elif "維修" in text or "维修" in text or "更換" in text or "更换" in text:
        work_type = "maintenance"
    elif "call" in lower:
        work_type = "ad-hoc"

    if any(word in text for word in ["更換", "更换", "壞", "坏", "維修", "维修"]):
        if "image" not in attachment_types:
            missing_items.append("照片记录")
    if any(word in lower for word in ["report", "pdf"]) and "pdf" not in attachment_types:
        missing_items.append("维修报告 PDF")
    if any(word in text for word in ["待", "未", "下次", "跟進", "跟进", "報價", "报价"]):
        next_actions.append("需要人工确认是否仍有待办")

    status = "已完成"
    if missing_items:
        status = "资料不足"
    elif next_actions:
        status = "需要跟进"
    elif not text:
        status = "未回复"

    return normalize_analysis(
        {
            "work_date": message.get("sent_at", "")[:10],
            "staff_name": message.get("sender", ""),
            "site": "",
            "work_type": work_type,
            "summary": text[:240],
            "result": "已回复" if text else "",
            "completion_status": status,
            "missing_items": missing_items,
            "next_actions": next_actions,
            "reminder_text": "",
        },
        message,
        attachments,
        rules,
    )


def normalize_analysis(
    analysis: dict[str, Any],
    message: dict[str, Any],
    attachments: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    result = dict(analysis)
    result["work_date"] = to_simplified_text(str(result.get("work_date") or message.get("sent_at", "")[:10]))
    result["staff_name"] = to_simplified_text(str(result.get("staff_name") or message.get("sender") or ""))
    result["site"] = to_simplified_text(str(result.get("site") or ""))
    result["work_type"] = to_simplified_text(str(result.get("work_type") or "other"))
    result["summary"] = to_simplified_text(str(result.get("summary") or ""))
    result["result"] = to_simplified_text(str(result.get("result") or ""))
    result["completion_status"] = _valid_status(str(result.get("completion_status") or "待人工确认"))
    result["missing_items"] = [to_simplified_text(item) for item in _list_of_strings(result.get("missing_items"))]
    result["next_actions"] = [to_simplified_text(item) for item in _list_of_strings(result.get("next_actions"))]
    result["reminder_text"] = to_simplified_text(str(result.get("reminder_text") or ""))
    if result["missing_items"] and result["completion_status"] == "已完成":
        result["completion_status"] = "资料不足"
    if (result["missing_items"] or result["completion_status"] in {"未回复", "资料不足", "需要跟进"}) and not result["reminder_text"]:
        target = result["staff_name"] or "相关同事"
        reason = "、".join(result["missing_items"] or result["next_actions"] or [result["completion_status"]])
        result["reminder_text"] = f"@{target} 请补充/确认：{reason}"
    return apply_completion_score(result)


def _valid_status(value: str) -> str:
    normalized = to_simplified_text(value)
    aliases = {
        "已完成": "已完成",
        "资料不足": "资料不足",
        "需要跟进": "需要跟进",
        "待人工确认": "待人工确认",
        "未回复": "未回复",
    }
    return aliases.get(normalized, "待人工确认")


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def to_simplified_text(value: str) -> str:
    replacements = {
        "photo_record": "照片记录",
        "report_pdf": "维修报告 PDF",
        "route_plan": "路线图或平面图",
        "delivery_photo": "送货照片",
        "photo_before": "更换前照片",
        "photo_during": "更换中照片",
        "photo_after": "更换后照片",
        "维修报告PDF": "维修报告 PDF",
        "維修報告PDF": "维修报告 PDF",
        "資料不足": "资料不足",
        "需要跟進": "需要跟进",
        "待人工確認": "待人工确认",
        "未回覆": "未回复",
        "已回覆": "已回复",
        "相關同事": "相关同事",
        "請補充": "请补充",
        "請補": "请补",
        "補充": "补充",
        "確認": "确认",
        "維修報告": "维修报告",
        "維修": "维修",
        "例檢": "例检",
        "送貨": "送货",
        "報價": "报价",
        "照片記錄": "照片记录",
        "記錄": "记录",
        "待辦": "待办",
        "報告": "报告",
        "掃描": "扫描",
        "測試": "测试",
        "商場": "商场",
        "車場": "车场",
        "會所": "会所",
        "顯示": "显示",
        "問題": "问题",
        "門磁": "门磁",
        "壞": "坏",
        "檢查": "检查",
        "更換": "更换",
        "無": "无",
        "後": "后",
        "號": "号",
        "補": "补",
        "線": "线",
        "對": "对",
        "樓": "楼",
        "電": "电",
        "機": "机",
        "時": "时",
        "與": "与",
        "並": "并",
    }
    text = value
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text
