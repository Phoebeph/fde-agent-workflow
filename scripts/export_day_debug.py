from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.database import Database, loads
from app.services.diagnostics import build_location_coverage_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export raw messages, repair records, reminders and diagnostics for one work date.",
    )
    parser.add_argument("work_date", help="Date in YYYY-MM-DD format, e.g. 2026-06-20")
    parser.add_argument("--output", help="Output JSON path. Defaults to DATA_ROOT/debug/debug_YYYY-MM-DD.json")
    args = parser.parse_args()

    db = Database(settings.database_path)
    db.init()
    output_path = Path(args.output) if args.output else settings.data_root / "debug" / f"debug_{args.work_date}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    messages = db.list_messages_for_date(args.work_date, limit=2000)
    repair_records = db.list_export_repair_records(args.work_date)
    payload = {
        "work_date": args.work_date,
        "database_path": str(settings.database_path),
        "counts": db.count_rows(),
        "raw_messages_count": len(messages),
        "repair_records_count": len(repair_records),
        "raw_messages": messages,
        "repair_records": repair_records,
        "attachment_checks": db.list_export_attachment_checks(args.work_date),
        "reminders": db.list_export_reminders(args.work_date),
        "run_records": _list_run_records_for_date(settings.database_path, args.work_date),
        "mock_records": _list_mock_records_for_date(settings.database_path, args.work_date),
        "location_diagnostics": build_location_coverage_report(
            messages=messages,
            repair_records=repair_records,
        ),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"debug_export={output_path}")
    print(f"raw_messages={payload['raw_messages_count']}")
    print(f"repair_records={payload['repair_records_count']}")
    print(f"possibly_missing_locations={payload['location_diagnostics']['possibly_missing_locations']}")


def _list_run_records_for_date(database_path: Path, work_date: str) -> list[dict[str, Any]]:
    with _connect(database_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM run_records
            WHERE substr(created_at, 1, 10) = ?
               OR message_summary LIKE ?
            ORDER BY created_at ASC
            """,
            (work_date, f"%{work_date}%"),
        ).fetchall()
    return [dict(row) for row in rows]


def _list_mock_records_for_date(database_path: Path, work_date: str) -> list[dict[str, Any]]:
    with _connect(database_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM mock_feishu_records
            WHERE fields_json LIKE ?
               OR substr(created_at, 1, 10) = ?
            ORDER BY updated_at ASC
            """,
            (f"%{work_date}%", work_date),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["fields"] = loads(item.pop("fields_json", "{}"), {})
        result.append(item)
    return result


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == "__main__":
    main()
