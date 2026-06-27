from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
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
        items = self.analyze_message_items(message=message, attachments=attachments, rules=rules)
        return items[0] if items else rule_based_analysis(message, attachments, rules)

    def analyze_message_items(
        self,
        *,
        message: dict[str, Any],
        attachments: list[dict[str, Any]],
        rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return rule_based_analysis_items(message, attachments, rules)

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You convert Hong Kong maintenance WhatsApp messages into strict JSON. "
                        "Return only one JSON object. Do not include markdown. "
                        "Use Simplified Chinese labels where status text is needed. "
                        "If one WhatsApp message contains multiple independent maintenance jobs, "
                        "return one item per job in the items array. Ignore standalone photo labels "
                        "or material labels such as 前/中/后/料 unless they include real work details."
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
                                "items": [
                                    {
                                        "work_date": "YYYY-MM-DD or empty string",
                                        "staff_name": "actual staff name if mentioned, otherwise sender",
                                        "site": "site/location if known",
                                        "work_type": "例检/ad-hoc/maintenance/delivery/quotation/other",
                                        "summary": "short maintenance summary for this one job",
                                        "result": "work result for this one job",
                                        "completion_status": "已完成|资料不足|需要跟进|待人工确认|未回复",
                                        "completion_score": "0-100 integer, higher means more complete",
                                        "completion_level": "高|较高|中|较低|低",
                                        "missing_items": ["missing photo/pdf/report/detail if any"],
                                        "next_actions": ["follow-up action if any"],
                                        "reminder_text": "WhatsApp reminder text if missing_items or follow-up is needed",
                                    }
                                ],
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
        return normalize_analysis_items(result, message, attachments, rules)

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

    needs_quote_photo = ("報價" in text or "报价" in text) and any(
        word in text for word in ["損壞", "损坏", "壞", "坏", "故障", "維修", "维修", "更換", "更换", "設備", "设备"]
    )
    needs_atal_photos = (
        "atal" in lower
        and any(word in text for word in ["安裝", "安装", "加裝", "加装", "更換", "更换", "換", "换"])
        and any(word in text for word in ["物料", "材料", "配件", "設備", "设备", "提供"])
    )
    needs_delivery_photo = any(word in text for word in ["送貨", "送货", "交貨", "交货", "簽收", "签收"])
    needs_hkis_logbook = "hkis" in lower and any(word in text for word in ["大潭", "淺水灣", "浅水湾", "Repulse Bay", "Tai Tam"])
    if needs_atal_photos:
        if sum(1 for value in attachment_types if value == "image") < 3:
            missing_items.append("更换前/更换中/更换后照片")
        if "pdf" not in attachment_types:
            missing_items.append("维修报告 PDF")
    elif needs_quote_photo or needs_delivery_photo:
        if "image" not in attachment_types:
            missing_items.append("送货照片" if needs_delivery_photo else "照片记录")
    elif needs_hkis_logbook and "image" not in attachment_types:
        missing_items.append("Logbook照片")
    if any(word in lower for word in ["ecall", "e-call", "e call"]) and any(word in text for word in ["額外收費", "额外收费", "收費", "收费"]):
        if "pdf" not in attachment_types:
            missing_items.append("维修报告 PDF")
    if any(word in lower for word in ["report", "pdf"]) and any(word in text for word in ["需", "需要", "後補", "后补", "請補", "请补", "有冇"]) and "pdf" not in attachment_types:
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
            "work_date": infer_work_date_from_text(text, str(message.get("sent_at", "")[:10])),
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


def rule_based_analysis_items(
    message: dict[str, Any],
    attachments: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = (message.get("text") or "").strip()
    chunks = split_work_item_text(text)
    if len(chunks) <= 1:
        return [rule_based_analysis(message, attachments, rules)]
    items = []
    for chunk in chunks:
        item_message = dict(message)
        item_message["text"] = chunk
        items.append(rule_based_analysis(item_message, attachments, rules))
    return items


def infer_work_date_from_text(text: str, fallback_date: str) -> str:
    match = re.search(r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", text)
    if not match:
        return fallback_date
    fallback_year = fallback_date[:4] if len(fallback_date) >= 4 else ""
    year_text = match.group(3)
    if year_text:
        year = int(year_text)
        if year < 100:
            year += 2000
    elif fallback_year.isdigit():
        year = int(fallback_year)
    else:
        return fallback_date
    try:
        return datetime(year, int(match.group(2)), int(match.group(1))).strftime("%Y-%m-%d")
    except ValueError:
        return fallback_date


def normalize_analysis_items(
    analysis: dict[str, Any],
    message: dict[str, Any],
    attachments: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chunks = split_work_item_text(str(message.get("text") or ""))
    raw_items = analysis.get("items")
    if isinstance(raw_items, list):
        normalized_items = [
            normalize_analysis(item, message, attachments, rules)
            for item in raw_items
            if isinstance(item, dict) and _has_meaningful_item_content(item)
        ]
        if normalized_items:
            return _append_missing_split_items(normalized_items, chunks, message, attachments, rules)
    if len(chunks) > 1:
        items = []
        for chunk in chunks:
            item_message = dict(message)
            item_message["text"] = chunk
            items.append(rule_based_analysis(item_message, attachments, rules))
        return items
    return [normalize_analysis(analysis, message, attachments, rules)]


def split_work_item_text(text: str) -> list[str]:
    lines = [line.strip(" \t-•⁠") for line in text.splitlines()]
    items: list[str] = []
    current_heading = ""
    current_date = ""
    for line in lines:
        if not line:
            continue
        if _looks_like_date_heading(line):
            current_date = line
            continue
        if _is_followup_detail_line(line) and items:
            items[-1] = f"{items[-1]}，{line}"
            continue
        if _looks_like_site_heading(line) and not _looks_like_work_line(line):
            current_heading = f"{current_date} {line}".strip()
            continue
        if _looks_like_work_line(line):
            heading = current_heading or current_date
            items.append(f"{heading} {line}".strip())
    return items or [text.strip()]


def _looks_like_date_heading(line: str) -> bool:
    compact = "".join(line.split())
    return bool(re.fullmatch(r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?", compact))


def _looks_like_site_heading(line: str) -> bool:
    if len(line) > 40:
        return False
    return bool(any(char.isalpha() for char in line) or any("\u4e00" <= char <= "\u9fff" for char in line))


def _looks_like_work_line(line: str) -> bool:
    lowered = line.lower()
    markers = [
        "cam",
        "camera",
        "disconnect",
        "speaker",
        "pos",
        "lift",
        "qr",
        "更換",
        "更换",
        "失靈",
        "失灵",
        "正常",
        "未能跟進",
        "未能跟进",
        "需再",
        "需報價",
        "需报价",
        "調教",
        "调教",
        "路線",
        "路线",
        "轉轉鏡",
        "转转镜",
        "重新過資料",
        "重新过资料",
        "等客試",
        "等客试",
        "測試",
        "测试",
        "例檢",
        "例检",
        "checklist",
    ]
    return any(marker in lowered or marker in line for marker in markers)


def _is_followup_detail_line(line: str) -> bool:
    normalized = "".join(line.split()).casefold()
    if not normalized:
        return False
    detail_markers = [
        "checklist已簽",
        "checklist已签",
        "checklist已交",
        "因天雨關係需再跟進",
        "因天雨关系需再跟进",
        "因天氣關係需再跟進",
        "因天气关系需再跟进",
        "需再跟進",
        "需再跟进",
    ]
    return any(marker in normalized for marker in detail_markers)


def _append_missing_split_items(
    normalized_items: list[dict[str, Any]],
    chunks: list[str],
    message: dict[str, Any],
    attachments: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(chunks) <= 1:
        return normalized_items
    existing_text = "\n".join(
        str(item.get("summary") or item.get("result") or item.get("site") or "")
        for item in normalized_items
    ).casefold()
    result = list(normalized_items)
    for chunk in chunks:
        if _chunk_is_covered(chunk, existing_text):
            continue
        item_message = dict(message)
        item_message["text"] = chunk
        result.append(rule_based_analysis(item_message, attachments, rules))
    return result


def _chunk_is_covered(chunk: str, existing_text: str) -> bool:
    tokens = _distinctive_tokens(chunk)
    if not tokens:
        return False
    return any(token in existing_text for token in tokens)


def _distinctive_tokens(text: str) -> list[str]:
    lowered = text.casefold()
    tokens = re.findall(r"[a-z]+[0-9]+|[a-z][\u4e00-\u9fff]|[a-z]{3,}|[0-9]{2,}", lowered)
    ignored = {"the", "soui", "cam", "pos", "wall", "normal", "control"}
    return [token for token in tokens if token not in ignored]


def _has_meaningful_item_content(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("site", "work_type", "summary", "result")
    ).strip()
    return len(text) >= 4


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
    if (
        result["staff_name"]
        and (result["missing_items"] or result["completion_status"] in {"未回复", "资料不足", "需要跟进"})
        and not result["reminder_text"]
    ):
        target = result["staff_name"]
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
