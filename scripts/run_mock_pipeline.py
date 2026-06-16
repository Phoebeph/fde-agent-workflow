from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.database import Database
from app.services.archive import archive_attachment
from app.services.completion import apply_schedule_completion
from app.services.deepseek import DeepSeekClient
from app.services.feishu import FeishuClient
from app.services.fingerprint import message_fingerprint
from app.services.rules import load_rules_from_xlsx


FIXTURE_PATH = ROOT / "fixtures" / "mock_whatsapp_messages.json"
RULES_PATH = Path("/Users/mac/Desktop/工作規則.xlsx")
DOWNLOADS_DIR = ROOT / "downloads"


def main() -> None:
    db = Database(settings.database_path)
    db.init()
    _import_rules_if_available(db)

    fixture = json.loads(FIXTURE_PATH.read_text())
    messages = _prepare_messages(fixture)
    insert_result = db.insert_messages(messages)
    attachment_result = _create_mock_attachments(db, messages)
    analysis_result = _run_analysis(db)

    result = {
        "mode": {
            "whatsapp": "mock",
            "feishu": "mock" if settings.feishu_mock_mode else "real_if_configured",
            "deepseek": "real" if settings.deepseek_enabled else "rule_based_fallback",
        },
        "messages": insert_result,
        "attachments": attachment_result,
        "analysis": analysis_result,
        "counts": db.count_rows(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _import_rules_if_available(db: Database) -> None:
    if RULES_PATH.exists():
        db.upsert_rules(load_rules_from_xlsx(RULES_PATH))


def _prepare_messages(fixture: dict[str, object]) -> list[dict[str, object]]:
    group_name = str(fixture["group_name"])
    rows: list[dict[str, object]] = []
    for item in fixture["messages"]:
        message = dict(item)
        fingerprint = message_fingerprint(
            group_name=group_name,
            sender=str(message["sender"]),
            sent_at=str(message["sent_at"]),
            text=str(message.get("text", "")),
            external_message_id=message.get("external_message_id"),
            attachment_hints=message.get("attachment_hints", []),
        )
        rows.append(
            {
                "group_name": group_name,
                "sender": message["sender"],
                "sent_at": message["sent_at"],
                "text": message.get("text", ""),
                "external_message_id": message.get("external_message_id"),
                "attachment_hints": message.get("attachment_hints", []),
                "raw_payload": message.get("raw_payload", {}),
                "has_attachments": message.get("has_attachments", False),
                "message_fingerprint": fingerprint,
            }
        )
    return rows


def _create_mock_attachments(db: Database, messages: list[dict[str, object]]) -> dict[str, int]:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    inserted = 0
    skipped = 0
    for row in messages:
        if not row.get("has_attachments"):
            continue
        message = db.get_message_by_fingerprint(str(row["message_fingerprint"]))
        if not message:
            skipped += 1
            continue
        attachment_type = _attachment_type(row)
        suffix = ".jpg" if attachment_type == "image" else ".pdf"
        filename = f"{row['external_message_id']}{suffix}"
        temp_path = DOWNLOADS_DIR / filename
        if not temp_path.exists():
            temp_path.write_bytes(f"mock attachment for {row['external_message_id']}\n".encode("utf-8"))
        archived = archive_attachment(
            str(temp_path),
            settings.archive_root,
            original_filename=filename,
            work_date=str(row["sent_at"])[:10],
            site="mock_site",
            staff_name=str(row["sender"]),
            work_type="mock_work",
            attachment_type=attachment_type,
        )
        if db.insert_attachment(
            {
                "raw_message_id": message["id"],
                "original_filename": archived.original_filename,
                "original_path": archived.original_path,
                "archive_filename": archived.archive_filename,
                "archive_path": archived.archive_path,
                "attachment_type": attachment_type,
                "sha256": archived.sha256,
                "size_bytes": archived.size_bytes,
            }
        ):
            inserted += 1
        else:
            skipped += 1
    return {"inserted": inserted, "skipped": skipped}


def _attachment_type(row: dict[str, object]) -> str:
    hints = row.get("attachment_hints") or []
    if isinstance(hints, list) and hints:
        first = hints[0]
        if isinstance(first, dict) and first.get("type"):
            return str(first["type"])
    return "other"


def _run_analysis(db: Database) -> dict[str, int]:
    deepseek = DeepSeekClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
    )
    feishu = FeishuClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        app_token=settings.feishu_app_token,
        table_id=settings.feishu_table_id,
        base_url=settings.feishu_base_url,
        upload_parent_type=settings.feishu_upload_parent_type,
        upload_parent_node=settings.feishu_upload_parent_node,
    )
    rules = db.list_rules()
    analyzed = 0
    feishu_synced = 0
    reminders_created = 0
    failed = 0
    for message in db.list_pending_messages(50):
        attachments = db.list_attachments_for_message(message["id"])
        try:
            analysis = deepseek.analyze_message(message=message, attachments=attachments, rules=rules)
            analysis = apply_schedule_completion(
                analysis=analysis,
                message=message,
                attachments=attachments,
                schedules=db.list_schedules_for_message(message),
            )
            fields = feishu.fields_for_repair_record(message, analysis, attachments)
            if feishu.enabled:
                if message.get("feishu_record_id"):
                    feishu.update_record(message["feishu_record_id"], fields)
                    feishu_record_id = message["feishu_record_id"]
                else:
                    feishu_record_id = feishu.create_record(fields)
            else:
                feishu_record_id = db.save_mock_feishu_record(fields, message.get("feishu_record_id"))
            record_id = db.save_repair_record(message["id"], analysis, feishu_record_id)
            if db.create_reminder_if_needed(record_id, analysis):
                reminders_created += 1
            analyzed += 1
            feishu_synced += 1
        except Exception:
            db.mark_message_retry(message["id"])
            failed += 1
    return {
        "analyzed": analyzed,
        "failed": failed,
        "feishu_synced": feishu_synced,
        "reminders_created": reminders_created,
    }


if __name__ == "__main__":
    main()
