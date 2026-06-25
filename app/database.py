from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    whatsapp_name TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    roles_json TEXT NOT NULL DEFAULT '[]',
    feishu_name TEXT,
    mention_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_principles (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL,
    sender TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    message_fingerprint TEXT NOT NULL UNIQUE,
    external_message_id TEXT,
    attachment_hints_json TEXT NOT NULL DEFAULT '[]',
    raw_payload_json TEXT NOT NULL DEFAULT '{}',
    has_attachments INTEGER NOT NULL DEFAULT 0,
    analysis_status TEXT NOT NULL DEFAULT 'pending',
    feishu_record_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_messages_sent_at ON raw_messages(sent_at);
CREATE INDEX IF NOT EXISTS idx_raw_messages_sender ON raw_messages(sender);
CREATE INDEX IF NOT EXISTS idx_raw_messages_analysis_status ON raw_messages(analysis_status);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    original_path TEXT NOT NULL,
    archive_filename TEXT NOT NULL DEFAULT '',
    archive_path TEXT NOT NULL,
    attachment_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    feishu_file_token TEXT,
    feishu_url TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id) ON DELETE CASCADE,
    UNIQUE(raw_message_id, sha256)
);

CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(raw_message_id);
CREATE INDEX IF NOT EXISTS idx_attachments_sha256 ON attachments(sha256);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_no TEXT,
    title TEXT NOT NULL,
    remind_content TEXT NOT NULL,
    trigger_keywords_json TEXT NOT NULL DEFAULT '[]',
    requirements_json TEXT NOT NULL DEFAULT '[]',
    source_file TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(title, source_file)
);

CREATE TABLE IF NOT EXISTS work_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_date TEXT NOT NULL,
    shift TEXT,
    staff_name TEXT NOT NULL,
    site TEXT,
    task_text TEXT NOT NULL,
    source_file TEXT,
    ocr_confidence REAL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_work_schedules_date_staff ON work_schedules(work_date, staff_name);

CREATE TABLE IF NOT EXISTS repair_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER,
    item_index INTEGER NOT NULL DEFAULT 0,
    work_schedule_id INTEGER,
    work_date TEXT,
    staff_name TEXT,
    site TEXT,
    work_type TEXT,
    summary TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    completion_status TEXT NOT NULL DEFAULT '待人工确认',
    completion_score INTEGER NOT NULL DEFAULT 0,
    completion_level TEXT NOT NULL DEFAULT '',
    missing_items_json TEXT NOT NULL DEFAULT '[]',
    next_actions_json TEXT NOT NULL DEFAULT '[]',
    feishu_record_id TEXT,
    human_review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id) ON DELETE SET NULL,
    FOREIGN KEY(work_schedule_id) REFERENCES work_schedules(id) ON DELETE SET NULL,
    UNIQUE(raw_message_id, item_index)
);

CREATE INDEX IF NOT EXISTS idx_repair_records_status ON repair_records(completion_status);
CREATE INDEX IF NOT EXISTS idx_repair_records_date_staff ON repair_records(work_date, staff_name);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repair_record_id INTEGER NOT NULL,
    target_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    sent_at TEXT,
    result_payload_json TEXT NOT NULL DEFAULT '{}',
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(repair_record_id) REFERENCES repair_records(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status);
CREATE INDEX IF NOT EXISTS idx_reminders_record ON reminders(repair_record_id);

CREATE TABLE IF NOT EXISTS mock_feishu_records (
    record_id TEXT PRIMARY KEY,
    fields_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_records (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    sender TEXT,
    message_summary TEXT,
    message_fingerprint TEXT,
    mock_feishu_record_id TEXT,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    analyzed_count INTEGER NOT NULL DEFAULT 0,
    feishu_synced_count INTEGER NOT NULL DEFAULT 0,
    reminders_created INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_records_created_at ON run_records(created_at);
CREATE INDEX IF NOT EXISTS idx_run_records_run_type ON run_records(run_type);
CREATE INDEX IF NOT EXISTS idx_run_records_status ON run_records(status);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_schedule_id INTEGER,
    raw_message_id INTEGER,
    event_type TEXT NOT NULL,
    sender TEXT NOT NULL,
    target_name TEXT,
    site TEXT,
    work_date TEXT,
    event_text TEXT NOT NULL DEFAULT '',
    event_payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(work_schedule_id) REFERENCES work_schedules(id) ON DELETE SET NULL,
    FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id) ON DELETE SET NULL,
    UNIQUE(raw_message_id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_task_events_schedule ON task_events(work_schedule_id);
CREATE INDEX IF NOT EXISTS idx_task_events_raw_message ON task_events(raw_message_id);
CREATE INDEX IF NOT EXISTS idx_task_events_type ON task_events(event_type);
CREATE INDEX IF NOT EXISTS idx_task_events_date_target ON task_events(work_date, target_name);

CREATE TABLE IF NOT EXISTS issue_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER UNIQUE,
    reported_by TEXT NOT NULL,
    work_date TEXT,
    site TEXT,
    issue_text TEXT NOT NULL DEFAULT '',
    issue_summary TEXT NOT NULL DEFAULT '',
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    converted_work_schedule_id INTEGER,
    decision_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id) ON DELETE SET NULL,
    FOREIGN KEY(converted_work_schedule_id) REFERENCES work_schedules(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_issue_records_status ON issue_records(status);
CREATE INDEX IF NOT EXISTS idx_issue_records_date ON issue_records(work_date);
CREATE INDEX IF NOT EXISTS idx_issue_records_reported_by ON issue_records(reported_by);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalized_export_date(sent_at: str, fallback_work_date: str) -> str:
    raw = sent_at.strip()
    if len(raw) >= 10 and raw[:4].isdigit() and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    match = re.search(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<year>\d{4})", raw)
    if match:
        first = int(match.group("a"))
        second = int(match.group("b"))
        year = int(match.group("year"))
        day = first
        month = second
        if first <= 12 and second > 12:
            month = first
            day = second
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return fallback_work_date[:10] if fallback_work_date else ""


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        attachment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(attachments)").fetchall()
        }
        if "archive_filename" not in attachment_columns:
            conn.execute("ALTER TABLE attachments ADD COLUMN archive_filename TEXT NOT NULL DEFAULT ''")
            rows = conn.execute("SELECT id, archive_path FROM attachments").fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE attachments SET archive_filename = ? WHERE id = ?",
                    (Path(row["archive_path"]).name, row["id"]),
                )
        staff_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(staff)").fetchall()
        }
        if "roles_json" not in staff_columns:
            conn.execute("ALTER TABLE staff ADD COLUMN roles_json TEXT NOT NULL DEFAULT '[]'")
        if "is_active" not in staff_columns:
            conn.execute("ALTER TABLE staff ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "notes" not in staff_columns:
            conn.execute("ALTER TABLE staff ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if "updated_at" not in staff_columns:
            conn.execute("ALTER TABLE staff ADD COLUMN updated_at TEXT")
        self._seed_default_principles(conn)
        site_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(sites)").fetchall()
        }
        if "aliases_json" not in site_columns:
            conn.execute("ALTER TABLE sites ADD COLUMN aliases_json TEXT NOT NULL DEFAULT '[]'")
        if "notes" not in site_columns:
            conn.execute("ALTER TABLE sites ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if "is_active" not in site_columns:
            conn.execute("ALTER TABLE sites ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "updated_at" not in site_columns:
            conn.execute("ALTER TABLE sites ADD COLUMN updated_at TEXT")
        repair_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(repair_records)").fetchall()
        }
        if "completion_score" not in repair_columns:
            conn.execute("ALTER TABLE repair_records ADD COLUMN completion_score INTEGER NOT NULL DEFAULT 0")
        if "completion_level" not in repair_columns:
            conn.execute("ALTER TABLE repair_records ADD COLUMN completion_level TEXT NOT NULL DEFAULT ''")
        if "item_index" not in repair_columns:
            conn.execute("ALTER TABLE repair_records ADD COLUMN item_index INTEGER NOT NULL DEFAULT 0")
        indexes = conn.execute("PRAGMA index_list(repair_records)").fetchall()
        unique_columns = {
            tuple(
                info["name"]
                for info in conn.execute(f"PRAGMA index_info({row['name']})").fetchall()
            )
            for row in indexes
            if row["unique"]
        }
        has_old_unique = ("raw_message_id",) in unique_columns
        has_item_unique = any(row["name"] == "idx_repair_records_raw_item_unique" for row in indexes)
        if has_old_unique and not has_item_unique:
            self._rebuild_repair_records_for_multiple_items(conn)
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_repair_records_raw_item_unique
            ON repair_records(raw_message_id, item_index)
            WHERE raw_message_id IS NOT NULL
            """
        )
        reminder_foreign_tables = {
            row["table"] for row in conn.execute("PRAGMA foreign_key_list(reminders)").fetchall()
        }
        if "repair_records_old" in reminder_foreign_tables:
            self._rebuild_reminders_after_repair_records_migration(conn)
        conn.execute(
            """
            UPDATE repair_records
            SET completion_score = CASE completion_status
                    WHEN '已完成' THEN 100
                    WHEN '资料不足' THEN 70
                    WHEN '資料不足' THEN 70
                    WHEN '需要跟进' THEN 45
                    WHEN '需要跟進' THEN 45
                    WHEN '未回复' THEN 0
                    WHEN '未回覆' THEN 0
                    ELSE completion_score
                END,
                completion_level = CASE completion_status
                    WHEN '已完成' THEN '高'
                    WHEN '资料不足' THEN '中'
                    WHEN '資料不足' THEN '中'
                    WHEN '需要跟进' THEN '较低'
                    WHEN '需要跟進' THEN '较低'
                    WHEN '未回复' THEN '低'
                    WHEN '未回覆' THEN '低'
                    ELSE completion_level
                END
            WHERE completion_score = 0 AND completion_level = ''
            """
        )

    def _rebuild_repair_records_for_multiple_items(self, conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE repair_records RENAME TO repair_records_old")
        conn.execute(
            """
            CREATE TABLE repair_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_message_id INTEGER,
                item_index INTEGER NOT NULL DEFAULT 0,
                work_schedule_id INTEGER,
                work_date TEXT,
                staff_name TEXT,
                site TEXT,
                work_type TEXT,
                summary TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                completion_status TEXT NOT NULL DEFAULT '待人工确认',
                completion_score INTEGER NOT NULL DEFAULT 0,
                completion_level TEXT NOT NULL DEFAULT '',
                missing_items_json TEXT NOT NULL DEFAULT '[]',
                next_actions_json TEXT NOT NULL DEFAULT '[]',
                feishu_record_id TEXT,
                human_review_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id) ON DELETE SET NULL,
                FOREIGN KEY(work_schedule_id) REFERENCES work_schedules(id) ON DELETE SET NULL,
                UNIQUE(raw_message_id, item_index)
            )
            """
        )
        old_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(repair_records_old)").fetchall()
        }
        item_expr = "item_index" if "item_index" in old_columns else "0"
        conn.execute(
            f"""
            INSERT INTO repair_records (
                id, raw_message_id, item_index, work_schedule_id, work_date, staff_name, site,
                work_type, summary, result, completion_status, completion_score,
                completion_level, missing_items_json, next_actions_json, feishu_record_id,
                human_review_status, created_at, updated_at
            )
            SELECT
                id, raw_message_id, {item_expr}, work_schedule_id, work_date, staff_name, site,
                work_type, summary, result, completion_status, completion_score,
                completion_level, missing_items_json, next_actions_json, feishu_record_id,
                human_review_status, created_at, updated_at
            FROM repair_records_old
            """
        )
        conn.execute("DROP TABLE repair_records_old")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repair_records_status ON repair_records(completion_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repair_records_date_staff ON repair_records(work_date, staff_name)")
        self._rebuild_reminders_after_repair_records_migration(conn)

    def _rebuild_reminders_after_repair_records_migration(self, conn: sqlite3.Connection) -> None:
        reminder_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()
        }
        required_columns = {
            "id",
            "repair_record_id",
            "target_name",
            "reason",
            "content",
            "status",
            "sent_at",
            "result_payload_json",
            "resolved_at",
            "created_at",
        }
        if not required_columns.issubset(reminder_columns):
            return
        conn.execute("ALTER TABLE reminders RENAME TO reminders_old")
        conn.execute(
            """
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repair_record_id INTEGER NOT NULL,
                target_name TEXT NOT NULL,
                reason TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                sent_at TEXT,
                result_payload_json TEXT NOT NULL DEFAULT '{}',
                resolved_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(repair_record_id) REFERENCES repair_records(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            INSERT INTO reminders (
                id, repair_record_id, target_name, reason, content, status,
                sent_at, result_payload_json, resolved_at, created_at
            )
            SELECT
                id, repair_record_id, target_name, reason, content, status,
                sent_at, result_payload_json, resolved_at, created_at
            FROM reminders_old
            WHERE repair_record_id IN (SELECT id FROM repair_records)
            """
        )
        conn.execute("DROP TABLE reminders_old")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_record ON reminders(repair_record_id)")

    def _seed_default_principles(self, conn: sqlite3.Connection) -> None:
        now = utc_now()
        defaults = {
            "task_source_policy": {
                "value": "只有已确认派工人员的明确派工消息自动生成正式任务",
                "description": "普通成员的问题消息先进入待确认线索，不直接变成正式任务。",
            },
            "ordinary_issue_policy": {
                "value": "普通成员发现的问题先记录为待确认事项，等待派工人员确认",
                "description": "避免把普通成员的现场描述误判为正式派工。",
            },
            "unconfirmed_issue_reminder_hours": {
                "value": 24,
                "description": "普通成员问题线索超过多少小时未确认时提醒管理人员。",
            },
            "unconfirmed_issue_close_days": {
                "value": 7,
                "description": "普通成员问题线索超过多少天仍未确认时保留记录但停止反复提醒。",
            },
        }
        for key, item in defaults.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO system_principles (
                    key, value_json, description, updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (key, dumps(item["value"]), item["description"], now),
            )
        conn.execute(
            """
            UPDATE repair_records
            SET completion_level = CASE
                    WHEN completion_score >= 85 THEN '高'
                    WHEN completion_score >= 70 THEN '较高'
                    WHEN completion_score >= 50 THEN '中'
                    WHEN completion_score >= 30 THEN '较低'
                    ELSE '低'
                END
            """
        )

    def insert_messages(self, messages: list[dict[str, Any]]) -> dict[str, int]:
        inserted = 0
        skipped = 0
        now = utc_now()
        with self.connect() as conn:
            for msg in messages:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO raw_messages (
                        group_name, sender, sent_at, text, message_fingerprint,
                        external_message_id, attachment_hints_json, raw_payload_json,
                        has_attachments, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        msg["group_name"],
                        msg["sender"],
                        msg["sent_at"],
                        msg.get("text", ""),
                        msg["message_fingerprint"],
                        msg.get("external_message_id"),
                        dumps(msg.get("attachment_hints", [])),
                        dumps(msg.get("raw_payload", {})),
                        1 if msg.get("has_attachments") else 0,
                        now,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1
        return {"inserted": inserted, "skipped": skipped}

    def list_download_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT rm.*
                FROM raw_messages rm
                WHERE rm.has_attachments = 1
                  AND NOT EXISTS (
                    SELECT 1 FROM attachments a WHERE a.raw_message_id = rm.id
                  )
                ORDER BY rm.sent_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def list_recent_messages(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM raw_messages
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def list_messages_for_date(self, work_date: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM raw_messages
                WHERE substr(sent_at, 1, 10) = ?
                ORDER BY sent_at ASC, id ASC
                LIMIT ?
                """,
                (work_date, limit),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def count_rows(self) -> dict[str, int]:
        tables = [
            "raw_messages",
            "attachments",
            "rules",
            "work_schedules",
            "repair_records",
            "reminders",
            "mock_feishu_records",
            "run_records",
            "task_events",
            "issue_records",
        ]
        counts: dict[str, int] = {}
        with self.connect() as conn:
            for table in tables:
                row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                counts[table] = int(row["count"])
        return counts

    def get_message_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM raw_messages WHERE message_fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        return self._message_row(row) if row else None

    def get_message_by_external_id(self, external_message_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM raw_messages
                WHERE external_message_id = ?
                ORDER BY sent_at DESC, id DESC
                LIMIT 1
                """,
                (external_message_id,),
            ).fetchone()
        return self._message_row(row) if row else None

    def list_messages_by_fingerprints(self, fingerprints: list[str]) -> list[dict[str, Any]]:
        if not fingerprints:
            return []
        placeholders = ",".join("?" for _ in fingerprints)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM raw_messages
                WHERE message_fingerprint IN ({placeholders})
                ORDER BY sent_at ASC, id ASC
                """,
                tuple(fingerprints),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def insert_attachment(self, attachment: dict[str, Any]) -> bool:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO attachments (
                    raw_message_id, original_filename, original_path, archive_filename, archive_path,
                    attachment_type, sha256, size_bytes, feishu_file_token,
                    feishu_url, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment["raw_message_id"],
                    attachment["original_filename"],
                    attachment["original_path"],
                    attachment.get("archive_filename") or Path(attachment["archive_path"]).name,
                    attachment["archive_path"],
                    attachment["attachment_type"],
                    attachment["sha256"],
                    attachment["size_bytes"],
                    attachment.get("feishu_file_token"),
                    attachment.get("feishu_url"),
                    now,
                ),
            )
        return bool(cur.rowcount)

    def upsert_rules(self, rules: list[dict[str, Any]]) -> dict[str, int]:
        inserted = 0
        updated = 0
        now = utc_now()
        with self.connect() as conn:
            for rule in rules:
                cur = conn.execute(
                    """
                    INSERT INTO rules (
                        item_no, title, remind_content, trigger_keywords_json,
                        requirements_json, source_file, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(title, source_file) DO UPDATE SET
                        item_no = excluded.item_no,
                        remind_content = excluded.remind_content,
                        trigger_keywords_json = excluded.trigger_keywords_json,
                        requirements_json = excluded.requirements_json
                    """,
                    (
                        rule.get("item_no"),
                        rule["title"],
                        rule["remind_content"],
                        dumps(rule.get("trigger_keywords", [])),
                        dumps(rule.get("requirements", [])),
                        rule["source_file"],
                        now,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    updated += 1
        return {"upserted": inserted + updated}

    def list_rules(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM rules ORDER BY id ASC").fetchall()
        return [
            {
                "id": row["id"],
                "item_no": row["item_no"],
                "title": row["title"],
                "remind_content": row["remind_content"],
                "trigger_keywords": loads(row["trigger_keywords_json"], []),
                "requirements": loads(row["requirements_json"], []),
                "source_file": row["source_file"],
            }
            for row in rows
        ]

    def list_staff_configs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM staff
                ORDER BY is_active DESC, name ASC
                """
            ).fetchall()
        return [self._staff_row(row) for row in rows]

    def has_staff_configs(self) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM staff LIMIT 1").fetchone()
        return bool(row)

    def upsert_staff_config(self, staff: dict[str, Any]) -> int:
        now = utc_now()
        with self.connect() as conn:
            if staff.get("id"):
                existing = conn.execute(
                    "SELECT id FROM staff WHERE id = ?",
                    (staff["id"],),
                ).fetchone()
                if not existing:
                    raise ValueError("staff id not found")
                conn.execute(
                    """
                    UPDATE staff
                    SET name = ?,
                        whatsapp_name = ?,
                        aliases_json = ?,
                        roles_json = ?,
                        feishu_name = ?,
                        mention_name = ?,
                        is_active = ?,
                        notes = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        staff["name"],
                        staff.get("whatsapp_name"),
                        dumps(staff.get("aliases", [])),
                        dumps(staff.get("roles", [])),
                        staff.get("feishu_name"),
                        staff.get("mention_name"),
                        1 if staff.get("is_active", True) else 0,
                        staff.get("notes", ""),
                        now,
                        staff["id"],
                    ),
                )
                return int(staff["id"])
            conn.execute(
                """
                INSERT INTO staff (
                    name, whatsapp_name, aliases_json, roles_json,
                    feishu_name, mention_name, is_active, notes,
                    updated_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    whatsapp_name = excluded.whatsapp_name,
                    aliases_json = excluded.aliases_json,
                    roles_json = excluded.roles_json,
                    feishu_name = excluded.feishu_name,
                    mention_name = excluded.mention_name,
                    is_active = excluded.is_active,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (
                    staff["name"],
                    staff.get("whatsapp_name"),
                    dumps(staff.get("aliases", [])),
                    dumps(staff.get("roles", [])),
                    staff.get("feishu_name"),
                    staff.get("mention_name"),
                    1 if staff.get("is_active", True) else 0,
                    staff.get("notes", ""),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT id FROM staff WHERE name = ?", (staff["name"],)).fetchone()
        return int(row["id"])

    def set_staff_active(self, staff_id: int, is_active: bool) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE staff
                SET is_active = ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if is_active else 0, utc_now(), staff_id),
            )
        return bool(cur.rowcount)

    def list_staff_names_for_role(self, role: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM staff
                WHERE is_active = 1
                ORDER BY name ASC
                """
            ).fetchall()
        names = []
        for row in rows:
            data = self._staff_row(row)
            if role not in data["roles"]:
                continue
            candidates = [data.get("whatsapp_name") or data["name"], *data.get("aliases", [])]
            for candidate in candidates:
                value = str(candidate).strip()
                if value and value not in names:
                    names.append(value)
        return names

    def list_site_configs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sites
                ORDER BY is_active DESC, name ASC
                """
            ).fetchall()
        return [self._site_row(row) for row in rows]

    def upsert_site_config(self, site: dict[str, Any]) -> int:
        now = utc_now()
        aliases = site.get("aliases", [])
        with self.connect() as conn:
            if site.get("id"):
                existing = conn.execute("SELECT id FROM sites WHERE id = ?", (site["id"],)).fetchone()
                if not existing:
                    raise ValueError("site id not found")
                conn.execute(
                    """
                    UPDATE sites
                    SET name = ?, aliases_json = ?, notes = ?, is_active = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        site["name"],
                        dumps(aliases),
                        site.get("notes", ""),
                        1 if site.get("is_active", True) else 0,
                        now,
                        site["id"],
                    ),
                )
                return int(site["id"])
            conn.execute(
                """
                INSERT INTO sites (name, aliases_json, notes, is_active, updated_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    aliases_json = excluded.aliases_json,
                    notes = excluded.notes,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (
                    site["name"],
                    dumps(aliases),
                    site.get("notes", ""),
                    1 if site.get("is_active", True) else 0,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT id FROM sites WHERE name = ?", (site["name"],)).fetchone()
        return int(row["id"])

    def set_site_active(self, site_id: int, is_active: bool) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE sites
                SET is_active = ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if is_active else 0, utc_now(), site_id),
            )
        return bool(cur.rowcount)

    def resolve_site_name(self, value: str) -> str:
        candidate = str(value or "").strip()
        if not candidate:
            return candidate
        normalized = candidate.casefold()
        for site in self.list_site_configs():
            if not site.get("is_active", True):
                continue
            aliases = [site.get("name"), *site.get("aliases", [])]
            if any(str(alias or "").strip().casefold() == normalized for alias in aliases):
                return str(site.get("name") or candidate)
        return candidate

    def match_site_in_text(self, text: str) -> dict[str, Any] | None:
        haystack = str(text or "").casefold()
        if not haystack:
            return None
        candidates: list[tuple[int, dict[str, Any], str]] = []
        for site in self.list_site_configs():
            if not site.get("is_active", True):
                continue
            for alias in [site.get("name"), *site.get("aliases", [])]:
                value = str(alias or "").strip()
                if not value:
                    continue
                if value.casefold() in haystack:
                    candidates.append((len(value), site, value))
        if not candidates:
            return None
        _, site, matched = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        return {"name": site["name"], "matched": matched, "site": site}

    def resolve_staff_name(self, name: str) -> str:
        candidate = str(name or "").strip()
        if not candidate:
            return candidate
        normalized = candidate.casefold()
        for staff in self.list_staff_configs():
            if not staff.get("is_active", True):
                continue
            aliases = [
                staff.get("name"),
                staff.get("whatsapp_name"),
                staff.get("feishu_name"),
                staff.get("mention_name"),
                *staff.get("aliases", []),
            ]
            if any(str(alias or "").strip().casefold() == normalized for alias in aliases):
                return str(staff.get("feishu_name") or staff.get("name") or candidate)
        return candidate

    def list_system_principles(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM system_principles
                ORDER BY key ASC
                """
            ).fetchall()
        return [
            {
                "key": row["key"],
                "value": loads(row["value_json"], None),
                "description": row["description"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def update_system_principles(self, principles: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            for key, value in principles.items():
                existing = conn.execute(
                    "SELECT description FROM system_principles WHERE key = ?",
                    (key,),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO system_principles (
                        key, value_json, description, updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        key,
                        dumps(value),
                        existing["description"] if existing else "",
                        now,
                    ),
                )

    def save_run_record(self, record: dict[str, Any]) -> str:
        run_id = record.get("run_id") or f"run_{uuid.uuid4().hex[:16]}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO run_records (
                    run_id, run_type, status, sender, message_summary,
                    message_fingerprint, mock_feishu_record_id, inserted_count,
                    analyzed_count, feishu_synced_count, reminders_created,
                    error_summary, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    run_type = excluded.run_type,
                    status = excluded.status,
                    sender = excluded.sender,
                    message_summary = excluded.message_summary,
                    message_fingerprint = excluded.message_fingerprint,
                    mock_feishu_record_id = excluded.mock_feishu_record_id,
                    inserted_count = excluded.inserted_count,
                    analyzed_count = excluded.analyzed_count,
                    feishu_synced_count = excluded.feishu_synced_count,
                    reminders_created = excluded.reminders_created,
                    error_summary = excluded.error_summary
                """
                ,
                (
                    run_id,
                    record["run_type"],
                    record["status"],
                    record.get("sender"),
                    record.get("message_summary"),
                    record.get("message_fingerprint"),
                    record.get("mock_feishu_record_id"),
                    int(record.get("inserted_count", 0)),
                    int(record.get("analyzed_count", 0)),
                    int(record.get("feishu_synced_count", 0)),
                    int(record.get("reminders_created", 0)),
                    record.get("error_summary"),
                    record.get("created_at") or utc_now(),
                ),
            )
        return run_id

    def list_run_records(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM run_records
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_run_record(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_records WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def insert_schedule_rows(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        now = utc_now()
        inserted = 0
        skipped = 0
        with self.connect() as conn:
            for row in rows:
                existing = conn.execute(
                    """
                    SELECT id FROM work_schedules
                    WHERE work_date = ?
                      AND staff_name = ?
                      AND COALESCE(site, '') = COALESCE(?, '')
                      AND task_text = ?
                      AND COALESCE(source_file, '') = COALESCE(?, '')
                    LIMIT 1
                    """,
                    (
                        row["work_date"],
                        row["staff_name"],
                        row.get("site"),
                        row["task_text"],
                        row.get("source_file"),
                    ),
                ).fetchone()
                if existing:
                    skipped += 1
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO work_schedules (
                        work_date, shift, staff_name, site, task_text,
                        source_file, ocr_confidence, review_status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["work_date"],
                        row.get("shift"),
                        row["staff_name"],
                        row.get("site"),
                        row["task_text"],
                        row.get("source_file"),
                        row.get("ocr_confidence"),
                        row.get("review_status", "pending"),
                        now,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
        return {"inserted": inserted, "skipped": skipped}

    def find_schedule_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        with self.connect() as conn:
            found = conn.execute(
                """
                SELECT * FROM work_schedules
                WHERE work_date = ?
                  AND staff_name = ?
                  AND COALESCE(site, '') = COALESCE(?, '')
                  AND task_text = ?
                  AND COALESCE(source_file, '') = COALESCE(?, '')
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    row["work_date"],
                    row["staff_name"],
                    row.get("site"),
                    row["task_text"],
                    row.get("source_file"),
                ),
            ).fetchone()
        return dict(found) if found else None

    def list_schedules_for_message(self, message: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
        work_date = str(message.get("sent_at") or "")[:10]
        sender = str(message.get("sender") or "")
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM work_schedules
                WHERE work_date = ?
                  AND (staff_name = ? OR staff_name LIKE ? OR ? LIKE '%' || staff_name || '%')
                ORDER BY id ASC
                LIMIT ?
                """,
                (work_date, sender, f"%{sender}%", sender, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_schedules_without_repair_records(self, work_date: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT ws.*
                FROM work_schedules ws
                WHERE ws.work_date = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM repair_records rr
                    WHERE rr.work_schedule_id = ws.id
                  )
                ORDER BY ws.work_date ASC, ws.staff_name ASC, ws.id ASC
                LIMIT ?
                """,
                (work_date, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_schedule_for_event(
        self,
        *,
        work_date: str | None,
        target_name: str | None,
        site: str | None,
    ) -> dict[str, Any] | None:
        if not work_date or not target_name:
            return None
        target = target_name.strip()
        site_value = (site or "").strip()
        with self.connect() as conn:
            if site_value:
                row = conn.execute(
                    """
                    SELECT * FROM work_schedules
                    WHERE work_date = ?
                      AND (staff_name = ? OR staff_name LIKE ? OR ? LIKE '%' || staff_name || '%')
                      AND COALESCE(site, '') = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (work_date, target, f"%{target}%", target, site_value),
                ).fetchone()
                if row:
                    return dict(row)
            row = conn.execute(
                """
                SELECT * FROM work_schedules
                WHERE work_date = ?
                  AND (staff_name = ? OR staff_name LIKE ? OR ? LIKE '%' || staff_name || '%')
                ORDER BY id DESC
                LIMIT 1
                """,
                (work_date, target, f"%{target}%", target),
            ).fetchone()
        return dict(row) if row else None

    def save_issue_record(self, issue: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO issue_records (
                    raw_message_id, reported_by, work_date, site,
                    issue_text, issue_summary, confidence,
                    status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    issue.get("raw_message_id"),
                    issue["reported_by"],
                    issue.get("work_date"),
                    issue.get("site"),
                    issue.get("issue_text", ""),
                    issue.get("issue_summary", ""),
                    issue.get("confidence"),
                    now,
                    now,
                ),
            )
            if cur.rowcount:
                issue_id = cur.lastrowid
                inserted = True
            else:
                row = conn.execute(
                    "SELECT id FROM issue_records WHERE raw_message_id IS ?",
                    (issue.get("raw_message_id"),),
                ).fetchone()
                issue_id = row["id"] if row else None
                inserted = False
        return {"id": issue_id, "inserted": inserted}

    def list_issue_records(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status and status != "all":
            where = "WHERE ir.status = ?"
            params.append(status)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ir.*, rm.sender, rm.sent_at, rm.text AS raw_text, ws.task_text AS converted_task_text
                FROM issue_records ir
                LEFT JOIN raw_messages rm ON rm.id = ir.raw_message_id
                LEFT JOIN work_schedules ws ON ws.id = ir.converted_work_schedule_id
                {where}
                ORDER BY ir.created_at DESC, ir.id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_issue_candidates(self, *, site: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        params: list[Any] = []
        site_filter = ""
        if site:
            site_filter = "AND COALESCE(site, '') = ?"
            params.append(site)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM issue_records
                WHERE status = 'pending'
                  {site_filter}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_issue_status(self, issue_id: int, status: str, note: str = "") -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE issue_records
                SET status = ?, decision_note = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, note, utc_now(), issue_id),
            )
        return bool(cur.rowcount)

    def convert_issue_to_schedule(self, issue_id: int, schedule: dict[str, Any], note: str = "") -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            issue = conn.execute(
                "SELECT * FROM issue_records WHERE id = ?",
                (issue_id,),
            ).fetchone()
            if not issue:
                return {"converted": False, "reason": "issue_not_found"}
            if issue["status"] == "converted" and issue["converted_work_schedule_id"]:
                return {
                    "converted": False,
                    "reason": "already_converted",
                    "work_schedule_id": issue["converted_work_schedule_id"],
                }
            cur = conn.execute(
                """
                INSERT INTO work_schedules (
                    work_date, shift, staff_name, site, task_text,
                    source_file, ocr_confidence, review_status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule["work_date"],
                    schedule.get("shift"),
                    schedule["staff_name"],
                    schedule.get("site"),
                    schedule["task_text"],
                    schedule.get("source_file", f"issue_record:{issue_id}"),
                    schedule.get("ocr_confidence", 0.9),
                    schedule.get("review_status", "confirmed"),
                    now,
                ),
            )
            schedule_id = int(cur.lastrowid)
            conn.execute(
                """
                UPDATE issue_records
                SET status = 'converted',
                    converted_work_schedule_id = ?,
                    decision_note = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (schedule_id, note, now, issue_id),
            )
        return {"converted": True, "work_schedule_id": schedule_id}

    def link_issue_to_schedule(self, issue_id: int, work_schedule_id: int, note: str = "") -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            issue = conn.execute(
                "SELECT * FROM issue_records WHERE id = ?",
                (issue_id,),
            ).fetchone()
            if not issue:
                return {"linked": False, "reason": "issue_not_found"}
            schedule = conn.execute(
                "SELECT * FROM work_schedules WHERE id = ?",
                (work_schedule_id,),
            ).fetchone()
            if not schedule:
                return {"linked": False, "reason": "schedule_not_found"}
            if issue["status"] == "converted" and issue["converted_work_schedule_id"]:
                return {
                    "linked": False,
                    "reason": "already_converted",
                    "work_schedule_id": issue["converted_work_schedule_id"],
                }
            conn.execute(
                """
                UPDATE issue_records
                SET status = 'converted',
                    converted_work_schedule_id = ?,
                    decision_note = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (work_schedule_id, note, now, issue_id),
            )
        return {"linked": True, "work_schedule_id": work_schedule_id}

    def save_task_event(self, event: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO task_events (
                    work_schedule_id, raw_message_id, event_type, sender,
                    target_name, site, work_date, event_text,
                    event_payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("work_schedule_id"),
                    event.get("raw_message_id"),
                    event["event_type"],
                    event["sender"],
                    event.get("target_name"),
                    event.get("site"),
                    event.get("work_date"),
                    event.get("event_text", ""),
                    dumps(event.get("event_payload", {})),
                    now,
                ),
            )
            if cur.rowcount:
                event_id = cur.lastrowid
                inserted = True
            else:
                row = conn.execute(
                    """
                    SELECT id FROM task_events
                    WHERE raw_message_id IS ?
                      AND event_type = ?
                    LIMIT 1
                    """,
                    (event.get("raw_message_id"), event["event_type"]),
                ).fetchone()
                event_id = row["id"] if row else None
                inserted = False
        return {"id": event_id, "inserted": inserted}

    def list_task_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT te.*, ws.task_text
                FROM task_events te
                LEFT JOIN work_schedules ws ON ws.id = te.work_schedule_id
                ORDER BY te.created_at DESC, te.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["event_payload"] = loads(data.pop("event_payload_json", "{}"), {})
            result.append(data)
        return result

    def list_pending_messages(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM raw_messages
                WHERE analysis_status IN ('pending', 'retry')
                ORDER BY sent_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def list_repair_records_needing_followup(
        self,
        *,
        work_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        statuses = ("未回复", "未回覆", "资料不足", "資料不足", "需要跟进", "需要跟進")
        params: list[Any] = list(statuses)
        date_filter = ""
        if work_date:
            date_filter = "AND rr.work_date = ?"
            params.append(work_date)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT rr.*, ws.task_text
                FROM repair_records rr
                LEFT JOIN work_schedules ws ON ws.id = rr.work_schedule_id
                WHERE rr.completion_status IN ({",".join("?" for _ in statuses)})
                  AND rr.raw_message_id IS NOT NULL
                  {date_filter}
                ORDER BY rr.work_date ASC, rr.staff_name ASC, rr.id ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        records = []
        for row in rows:
            record = dict(row)
            record["missing_items"] = loads(record.pop("missing_items_json", "[]"), [])
            record["next_actions"] = loads(record.pop("next_actions_json", "[]"), [])
            records.append(record)
        return records

    def list_attachments_for_message(self, raw_message_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE raw_message_id = ? ORDER BY id ASC",
                (raw_message_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_repair_record(
        self,
        raw_message_id: int,
        analysis: dict[str, Any],
        feishu_record_id: str | None = None,
        item_index: int = 0,
    ) -> int:
        now = utc_now()
        missing_items = analysis.get("missing_items", []) or []
        next_actions = analysis.get("next_actions", []) or []
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO repair_records (
                    raw_message_id, item_index, work_schedule_id, work_date, staff_name, site,
                    work_type, summary, result, completion_status,
                    completion_score, completion_level,
                    missing_items_json, next_actions_json, feishu_record_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_message_id, item_index) DO UPDATE SET
                    work_schedule_id = excluded.work_schedule_id,
                    work_date = excluded.work_date,
                    staff_name = excluded.staff_name,
                    site = excluded.site,
                    work_type = excluded.work_type,
                    summary = excluded.summary,
                    result = excluded.result,
                    completion_status = excluded.completion_status,
                    completion_score = excluded.completion_score,
                    completion_level = excluded.completion_level,
                    missing_items_json = excluded.missing_items_json,
                    next_actions_json = excluded.next_actions_json,
                    feishu_record_id = COALESCE(excluded.feishu_record_id, repair_records.feishu_record_id),
                    updated_at = excluded.updated_at
                """,
                (
                    raw_message_id,
                    item_index,
                    analysis.get("work_schedule_id"),
                    analysis.get("work_date"),
                    analysis.get("staff_name"),
                    analysis.get("site"),
                    analysis.get("work_type"),
                    analysis.get("summary", ""),
                    analysis.get("result", ""),
                    analysis.get("completion_status", "待人工确认"),
                    int(analysis.get("completion_score", 0) or 0),
                    analysis.get("completion_level", ""),
                    dumps(missing_items),
                    dumps(next_actions),
                    feishu_record_id,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM repair_records WHERE raw_message_id = ? AND item_index = ?",
                (raw_message_id, item_index),
            ).fetchone()
            if feishu_record_id:
                conn.execute(
                    """
                    UPDATE raw_messages
                    SET analysis_status = 'done', feishu_record_id = ?
                    WHERE id = ?
                    """,
                    (feishu_record_id, raw_message_id),
                )
            else:
                conn.execute(
                    "UPDATE raw_messages SET analysis_status = 'done' WHERE id = ?",
                    (raw_message_id,),
                )
        return int(row["id"])

    def delete_repair_records_for_message(self, raw_message_id: int) -> int:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT feishu_record_id FROM repair_records
                WHERE raw_message_id = ? AND feishu_record_id IS NOT NULL
                """,
                (raw_message_id,),
            ).fetchall()
            record_ids = [row["feishu_record_id"] for row in rows if row["feishu_record_id"]]
            deleted = conn.execute(
                "DELETE FROM repair_records WHERE raw_message_id = ?",
                (raw_message_id,),
            ).rowcount
            for record_id in record_ids:
                conn.execute("DELETE FROM mock_feishu_records WHERE record_id = ?", (record_id,))
            conn.execute(
                "UPDATE raw_messages SET feishu_record_id = NULL WHERE id = ?",
                (raw_message_id,),
            )
        return int(deleted or 0)

    def list_repair_records_for_message(self, raw_message_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM repair_records
                WHERE raw_message_id = ?
                ORDER BY item_index ASC, id ASC
                """,
                (raw_message_id,),
            ).fetchall()
        records = []
        for row in rows:
            record = dict(row)
            record["missing_items"] = loads(record.pop("missing_items_json", "[]"), [])
            record["next_actions"] = loads(record.pop("next_actions_json", "[]"), [])
            records.append(record)
        return records

    def list_export_repair_records(self, work_date: str, site: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        site_filter = ""
        if site:
            site_filter = "AND COALESCE(rr.site, '') = ?"
            params.append(site)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    rr.*,
                    rm.sent_at AS raw_export_sent_at,
                    rm.sent_at AS whatsapp_sent_at,
                    rm.sender AS whatsapp_sender,
                    rm.text AS whatsapp_text,
                    rm.message_fingerprint,
                    ws.task_text AS schedule_task_text
                FROM repair_records rr
                LEFT JOIN raw_messages rm ON rm.id = rr.raw_message_id
                LEFT JOIN work_schedules ws ON ws.id = rr.work_schedule_id
                WHERE 1 = 1
                  {site_filter}
                ORDER BY COALESCE(rr.site, ''), rr.staff_name, rr.id
                """,
                tuple(params),
            ).fetchall()
        records = []
        for row in rows:
            record = dict(row)
            record["export_date"] = _normalized_export_date(
                str(record.pop("raw_export_sent_at") or ""),
                str(record.get("work_date") or ""),
            )
            if record["export_date"] != work_date:
                continue
            record["missing_items"] = loads(record.pop("missing_items_json", "[]"), [])
            record["next_actions"] = loads(record.pop("next_actions_json", "[]"), [])
            records.append(record)
        return records

    def list_export_attachment_checks(self, work_date: str, site: str | None = None) -> list[dict[str, Any]]:
        records = self.list_export_repair_records(work_date, site)
        with self.connect() as conn:
            for record in records:
                raw_message_id = record.get("raw_message_id")
                attachments = []
                if raw_message_id:
                    attachments = [
                        dict(row)
                        for row in conn.execute(
                            "SELECT * FROM attachments WHERE raw_message_id = ? ORDER BY id ASC",
                            (raw_message_id,),
                        ).fetchall()
                    ]
                record["attachments"] = attachments
        return records

    def list_export_reminders(self, work_date: str, site: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        site_filter = ""
        if site:
            site_filter = "AND COALESCE(rr.site, '') = ?"
            params.append(site)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    r.*,
                    rm.sent_at AS raw_export_sent_at,
                    rr.work_date,
                    rr.staff_name,
                    rr.site,
                    rr.summary,
                    rr.completion_status
                FROM reminders r
                JOIN repair_records rr ON rr.id = r.repair_record_id
                LEFT JOIN raw_messages rm ON rm.id = rr.raw_message_id
                WHERE 1 = 1
                  {site_filter}
                ORDER BY COALESCE(rr.site, ''), r.created_at ASC, r.id ASC
                """,
                tuple(params),
            ).fetchall()
        reminders = []
        for row in rows:
            reminder = dict(row)
            reminder["export_date"] = _normalized_export_date(
                str(reminder.pop("raw_export_sent_at") or ""),
                str(reminder.get("work_date") or ""),
            )
            if reminder["export_date"] != work_date:
                continue
            reminder["result_payload"] = loads(reminder.pop("result_payload_json", "{}"), {})
            reminders.append(reminder)
        return reminders

    def cleanup_mock_records_by_whatsapp_texts(self, texts: set[str]) -> dict[str, int]:
        normalized_texts = {"".join(text.split()) for text in texts if text.strip()}
        if not normalized_texts:
            return {"mock_records_deleted": 0, "repair_records_deleted": 0}
        mock_deleted = 0
        repair_deleted = 0
        with self.connect() as conn:
            mock_rows = conn.execute("SELECT record_id, fields_json FROM mock_feishu_records").fetchall()
            record_ids = []
            for row in mock_rows:
                fields = loads(row["fields_json"], {})
                original_text = "".join(str(fields.get("WhatsApp原文") or "").split())
                if original_text in normalized_texts:
                    record_ids.append(row["record_id"])
            for record_id in record_ids:
                repair_deleted += int(
                    conn.execute(
                        "DELETE FROM repair_records WHERE feishu_record_id = ?",
                        (record_id,),
                    ).rowcount
                    or 0
                )
                mock_deleted += int(
                    conn.execute(
                        "DELETE FROM mock_feishu_records WHERE record_id = ?",
                        (record_id,),
                    ).rowcount
                    or 0
                )
        return {
            "mock_records_deleted": mock_deleted,
            "repair_records_deleted": repair_deleted,
        }

    def save_schedule_gap_record(
        self,
        schedule: dict[str, Any],
        analysis: dict[str, Any],
        feishu_record_id: str | None = None,
    ) -> int:
        now = utc_now()
        missing_items = analysis.get("missing_items", []) or []
        next_actions = analysis.get("next_actions", []) or []
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM repair_records
                WHERE work_schedule_id = ? AND raw_message_id IS NULL
                LIMIT 1
                """,
                (schedule["id"],),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE repair_records
                    SET work_date = ?, staff_name = ?, site = ?, work_type = ?,
                        summary = ?, result = ?, completion_status = ?,
                        completion_score = ?, completion_level = ?,
                        missing_items_json = ?, next_actions_json = ?,
                        feishu_record_id = COALESCE(?, feishu_record_id),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        analysis.get("work_date"),
                        analysis.get("staff_name"),
                        analysis.get("site"),
                        analysis.get("work_type"),
                        analysis.get("summary", ""),
                        analysis.get("result", ""),
                        analysis.get("completion_status", "未回复"),
                        int(analysis.get("completion_score", 0) or 0),
                        analysis.get("completion_level", ""),
                        dumps(missing_items),
                        dumps(next_actions),
                        feishu_record_id,
                        now,
                        existing["id"],
                    ),
                )
                return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO repair_records (
                    raw_message_id, work_schedule_id, work_date, staff_name, site,
                    work_type, summary, result, completion_status,
                    completion_score, completion_level,
                    missing_items_json, next_actions_json, feishu_record_id,
                    created_at, updated_at
                )
                VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule["id"],
                    analysis.get("work_date"),
                    analysis.get("staff_name"),
                    analysis.get("site"),
                    analysis.get("work_type"),
                    analysis.get("summary", ""),
                    analysis.get("result", ""),
                    analysis.get("completion_status", "未回复"),
                    int(analysis.get("completion_score", 0) or 0),
                    analysis.get("completion_level", ""),
                    dumps(missing_items),
                    dumps(next_actions),
                    feishu_record_id,
                    now,
                    now,
                ),
            )
        return int(cur.lastrowid)

    def save_mock_feishu_record(self, fields: dict[str, Any], record_id: str | None = None) -> str:
        now = utc_now()
        target_record_id = record_id or f"mock_rec_{uuid.uuid4().hex[:16]}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO mock_feishu_records (
                    record_id, fields_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    fields_json = excluded.fields_json,
                    updated_at = excluded.updated_at
                """,
                (target_record_id, dumps(fields), now, now),
            )
        return target_record_id

    def list_mock_feishu_records(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM mock_feishu_records
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "record_id": row["record_id"],
                "fields": loads(row["fields_json"], {}),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def mark_message_retry(self, raw_message_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE raw_messages SET analysis_status = 'retry' WHERE id = ?",
                (raw_message_id,),
            )

    def mark_message_done(self, raw_message_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE raw_messages SET analysis_status = 'done' WHERE id = ?",
                (raw_message_id,),
            )

    def create_reminder_if_needed(self, repair_record_id: int, analysis: dict[str, Any]) -> bool:
        missing_items = analysis.get("missing_items", []) or []
        status = analysis.get("completion_status", "")
        if not missing_items and status not in {"未回复", "未回覆", "资料不足", "資料不足", "需要跟进", "需要跟進"}:
            return False
        target = analysis.get("staff_name") or "相关同事"
        reason = "、".join(missing_items) if missing_items else status
        content = analysis.get("reminder_text") or f"@{target} 请补充：{reason}"
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM reminders
                WHERE repair_record_id = ? AND status IN ('pending', 'sent')
                LIMIT 1
                """,
                (repair_record_id,),
            ).fetchone()
            if existing:
                return False
            conn.execute(
                """
                INSERT INTO reminders (
                    repair_record_id, target_name, reason, content, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (repair_record_id, target, reason, content, utc_now()),
            )
        return True

    def list_pending_reminders(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reminders
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_reminder_result(self, reminder_id: int, status: str, payload: dict[str, Any]) -> None:
        sent_at = utc_now() if status == "sent" else None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET status = ?, sent_at = COALESCE(?, sent_at), result_payload_json = ?
                WHERE id = ?
                """,
                (status, sent_at, dumps(payload), reminder_id),
            )

    @staticmethod
    def _message_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["attachment_hints"] = loads(data.pop("attachment_hints_json", "[]"), [])
        data["raw_payload"] = loads(data.pop("raw_payload_json", "{}"), {})
        data["has_attachments"] = bool(data["has_attachments"])
        return data

    @staticmethod
    def _staff_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["aliases"] = loads(data.pop("aliases_json", "[]"), [])
        data["roles"] = loads(data.pop("roles_json", "[]"), [])
        data["is_active"] = bool(data["is_active"])
        return data

    @staticmethod
    def _site_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["aliases"] = loads(data.pop("aliases_json", "[]"), [])
        data["is_active"] = bool(data["is_active"])
        return data
