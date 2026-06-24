from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.archive import safe_part


@dataclass(frozen=True)
class ExportResult:
    total_path: str
    site_paths: list[str]


def export_daily_workbook(
    *,
    db: Any,
    work_date: str,
    export_root: Path,
) -> ExportResult:
    base_dir = dated_export_dir(export_root, work_date)
    base_dir.mkdir(parents=True, exist_ok=True)

    total_path = base_dir / f"{work_date}_维修与提醒总表.xlsx"
    _write_export_workbook(
        total_path,
        repairs=db.list_export_repair_records(work_date),
        attachment_checks=db.list_export_attachment_checks(work_date),
        reminders=db.list_export_reminders(work_date),
    )

    site_paths = []
    sites = sorted(
        {
            str(record.get("site") or "unknown_site").strip() or "unknown_site"
            for record in db.list_export_repair_records(work_date)
        }
    )
    for site in sites:
        site_dir = base_dir / safe_part(site, "unknown_site")
        site_dir.mkdir(parents=True, exist_ok=True)
        site_path = site_dir / f"{work_date}_{safe_part(site, 'unknown_site')}_维修与提醒表.xlsx"
        _write_export_workbook(
            site_path,
            repairs=db.list_export_repair_records(work_date, site),
            attachment_checks=db.list_export_attachment_checks(work_date, site),
            reminders=db.list_export_reminders(work_date, site),
        )
        site_paths.append(str(site_path))

    return ExportResult(total_path=str(total_path), site_paths=site_paths)


def dated_export_dir(root: Path, work_date: str) -> Path:
    year = work_date[:4] if len(work_date) >= 4 and work_date[:4].isdigit() else "unknown_year"
    month = work_date[5:7] if len(work_date) >= 7 and work_date[5:7].isdigit() else "unknown_month"
    day = work_date[8:10] if len(work_date) >= 10 and work_date[8:10].isdigit() else "unknown_day"
    return root / year / month / day


def _write_export_workbook(
    path: Path,
    *,
    repairs: list[dict[str, Any]],
    attachment_checks: list[dict[str, Any]],
    reminders: list[dict[str, Any]],
) -> None:
    sheets = [
        ("维修记录", _repair_rows(repairs)),
        ("附件检查", _attachment_rows(attachment_checks)),
        ("提醒记录", _reminder_rows(reminders)),
    ]
    write_xlsx(path, sheets)


def _repair_rows(records: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = [[
        "维修记录ID",
        "归档日期",
        "实际工作日期",
        "备注",
        "同事",
        "地点",
        "工作类型",
        "AI摘要",
        "维修结果",
        "完成状态",
        "完成分数",
        "待办事项",
        "缺失资料",
        "WhatsApp消息时间",
        "WhatsApp原文",
    ]]
    for record in records:
        export_date = record.get("export_date") or record.get("work_date", "")
        actual_date = record.get("work_date", "")
        rows.append([
            record.get("id", ""),
            export_date,
            actual_date,
            _date_note(str(export_date or ""), str(actual_date or "")),
            record.get("staff_name", ""),
            record.get("site", ""),
            record.get("work_type", ""),
            record.get("summary", ""),
            record.get("result", ""),
            record.get("completion_status", ""),
            record.get("completion_score", ""),
            "、".join(record.get("next_actions", [])),
            "、".join(record.get("missing_items", [])),
            record.get("whatsapp_sent_at", ""),
            record.get("whatsapp_text", ""),
        ])
    return rows


def _attachment_rows(records: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = [[
        "维修记录ID",
        "归档日期",
        "实际工作日期",
        "地点",
        "同事",
        "是否需要照片",
        "是否需要维修报告PDF",
        "已归档文件名",
        "本地归档路径",
        "缺失资料",
    ]]
    for record in records:
        export_date = record.get("export_date") or record.get("work_date", "")
        missing_items = record.get("missing_items", [])
        attachments = record.get("attachments", [])
        rows.append([
            record.get("id", ""),
            export_date,
            record.get("work_date", ""),
            record.get("site", ""),
            record.get("staff_name", ""),
            "是" if _needs_photo(record) else "否",
            "是" if _needs_pdf(record) else "否",
            "\n".join(str(item.get("archive_filename") or "") for item in attachments),
            "\n".join(str(item.get("archive_path") or "") for item in attachments),
            "、".join(missing_items),
        ])
    return rows


def _reminder_rows(reminders: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = [[
        "提醒ID",
        "归档日期",
        "实际工作日期",
        "地点",
        "同事",
        "提醒对象",
        "提醒原因",
        "提醒内容",
        "状态",
        "发送时间",
        "是否已解决",
        "关联维修摘要",
    ]]
    for reminder in reminders:
        export_date = reminder.get("export_date") or reminder.get("work_date", "")
        rows.append([
            reminder.get("id", ""),
            export_date,
            reminder.get("work_date", ""),
            reminder.get("site", ""),
            reminder.get("staff_name", ""),
            reminder.get("target_name", ""),
            reminder.get("reason", ""),
            reminder.get("content", ""),
            reminder.get("status", ""),
            reminder.get("sent_at", ""),
            "是" if reminder.get("resolved_at") else "否",
            reminder.get("summary", ""),
        ])
    return rows


def _date_note(export_date: str, actual_date: str) -> str:
    if export_date and actual_date and export_date != actual_date:
        return f"{export_date} 记录的其他日期工作：实际工作日期 {actual_date}"
    return ""


def _needs_photo(record: dict[str, Any]) -> bool:
    text = " ".join([record.get("summary", ""), record.get("result", ""), " ".join(record.get("missing_items", []))])
    return any(marker in text for marker in ("照片", "photo", "Photo", "相片"))


def _needs_pdf(record: dict[str, Any]) -> bool:
    text = " ".join([record.get("summary", ""), record.get("result", ""), " ".join(record.get("missing_items", []))])
    return "PDF" in text.upper() or "维修报告" in text or "維修報告" in text


def write_xlsx(path: Path, sheets: list[tuple[str, list[list[Any]]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", _content_types(len(sheets)))
        workbook.writestr("_rels/.rels", _root_rels())
        workbook.writestr("xl/workbook.xml", _workbook_xml(sheets))
        workbook.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets)))
        for index, (_, rows) in enumerate(sheets, start=1):
            workbook.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows))


def _content_types(sheet_count: int) -> str:
    sheet_overrides = "\n".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{sheet_overrides}
</Types>"""


def _root_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbook_xml(sheets: list[tuple[str, list[list[Any]]]]) -> str:
    sheet_xml = "\n".join(
        f'<sheet name="{escape(_safe_sheet_name(name))}" sheetId="{index}" r:id="rId{index}"/>'
        for index, (name, _) in enumerate(sheets, start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>
{sheet_xml}
</sheets>
</workbook>"""


def _workbook_rels(sheet_count: int) -> str:
    rels = "\n".join(
        f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{rels}
</Relationships>"""


def _sheet_xml(rows: list[list[Any]]) -> str:
    row_xml = "\n".join(_row_xml(index, row) for index, row in enumerate(rows, start=1))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>
{row_xml}
</sheetData>
</worksheet>"""


def _row_xml(index: int, row: list[Any]) -> str:
    cells = "".join(_cell_xml(index, col_index, value) for col_index, value in enumerate(row, start=1))
    return f'<row r="{index}">{cells}</row>'


def _cell_xml(row_index: int, col_index: int, value: Any) -> str:
    cell_ref = f"{_column_name(col_index)}{row_index}"
    text = escape("" if value is None else str(value))
    return f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _safe_sheet_name(name: str) -> str:
    invalid = set("[]:*?/\\")
    cleaned = "".join("_" if char in invalid else char for char in name).strip()
    return (cleaned or "Sheet")[:31]
