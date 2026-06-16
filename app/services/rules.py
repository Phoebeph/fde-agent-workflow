from __future__ import annotations

from pathlib import Path

from app.services.xlsx_reader import read_xlsx


REQUIREMENT_KEYWORDS = {
    "photo_before": ["換前", "换前", "before"],
    "photo_during": ["換中", "换中", "during"],
    "photo_after": ["換後", "换后", "after"],
    "photo_record": ["photo record", "相片", "影相", "照片"],
    "report_pdf": ["pdf", "report", "報告", "报告", "scan", "掃描", "扫描"],
    "route_plan": ["平面圖", "平面图", "路線", "路线"],
    "delivery_photo": ["送貨相", "送货相", "delivery"],
}


def load_rules_from_xlsx(path: str | Path) -> list[dict[str, object]]:
    workbook_path = Path(path)
    sheets = read_xlsx(workbook_path)
    if not sheets:
        return []
    rows = sheets[0].rows
    if len(rows) <= 1:
        return []

    rules: list[dict[str, object]] = []
    for row in rows[1:]:
        item_no = _cell(row, 0)
        title = _cell(row, 1)
        remind = _cell(row, 2)
        if not title and not remind:
            continue
        combined = f"{title}\n{remind}".lower()
        requirements = [
            key
            for key, keywords in REQUIREMENT_KEYWORDS.items()
            if any(keyword.lower() in combined for keyword in keywords)
        ]
        trigger_keywords = _keywords_from_title(title)
        rules.append(
            {
                "item_no": item_no,
                "title": title or remind[:60],
                "remind_content": remind or title,
                "trigger_keywords": trigger_keywords,
                "requirements": requirements,
                "source_file": str(workbook_path),
            }
        )
    return rules


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return str(row[index]).strip()


def _keywords_from_title(title: str) -> list[str]:
    cleaned = title.replace("關於", " ").replace("关于", " ").replace("闗於", " ")
    tokens = []
    for part in cleaned.replace("，", ",").replace("、", ",").split(","):
        value = part.strip()
        if len(value) >= 2:
            tokens.append(value[:30])
    return tokens[:8]
