from __future__ import annotations

import re
from typing import Any

from app.services.deepseek import split_work_item_text


_DATE_PREFIX_RE = re.compile(r"^\s*(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|[0-9]{1,2}\s+[A-Za-z]{3}\s+[0-9]{4})\s*")
_LOCATION_STOPWORDS = {
    "checklist",
    "已簽",
    "已签",
    "已交",
    "正常",
    "更換",
    "更换",
    "重新",
    "因天",
    "需再",
    "完成",
}


def build_location_coverage_report(
    *,
    messages: list[dict[str, Any]],
    repair_records: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_items = []
    raw_locations: set[str] = set()
    for message in messages:
        for item in split_work_item_text(str(message.get("text") or "")):
            location = infer_location_from_item(item)
            if location:
                raw_locations.add(location)
            raw_items.append(
                {
                    "message_id": message.get("id"),
                    "sent_at": message.get("sent_at"),
                    "sender": message.get("sender"),
                    "candidate_location": location,
                    "content": item,
                }
            )

    record_items = [
        {
            "record_id": record.get("id"),
            "site": str(record.get("site") or "").strip(),
            "summary": record.get("summary", ""),
            "result": record.get("result", ""),
            "status": record.get("completion_status", ""),
        }
        for record in repair_records
    ]
    record_locations = {item["site"] for item in record_items if item["site"]}
    return {
        "raw_location_count": len(raw_locations),
        "record_location_count": len(record_locations),
        "raw_locations": sorted(raw_locations),
        "record_locations": sorted(record_locations),
        "possibly_missing_locations": sorted(raw_locations - record_locations),
        "raw_items": raw_items,
        "record_items": record_items,
    }


def infer_location_from_item(item: str) -> str:
    compact = " ".join(item.split())
    compact = _DATE_PREFIX_RE.sub("", compact).strip()
    if not compact:
        return ""
    if " " not in compact:
        return _first_location_token(compact)
    parts = compact.split()
    first = parts[0]
    second = parts[1] if len(parts) > 1 else ""
    if first.lower() == "the" and second:
        return f"{first} {second}"
    if first.lower() in {"trk", "tv", "g/f", "lcp"} and second:
        return f"{first} {second}"
    return _first_location_token(first)


def _first_location_token(value: str) -> str:
    cleaned = value.strip("：:,.，。()（）[]【】")
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if any(word.lower() in lowered for word in _LOCATION_STOPWORDS):
        return ""
    if len(cleaned) > 30:
        return ""
    return cleaned
