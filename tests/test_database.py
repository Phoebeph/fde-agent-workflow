from pathlib import Path
import tempfile
import unittest

from app.database import Database


class DatabaseTests(unittest.TestCase):
    def test_insert_messages_deduplicates_by_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Kei",
                "sent_at": "2026-06-10 18:00",
                "text": "完成",
                "message_fingerprint": "a" * 64,
                "has_attachments": False,
                "attachment_hints": [],
                "raw_payload": {},
            }

            self.assertEqual(db.insert_messages([message]), {"inserted": 1, "skipped": 0})
            self.assertEqual(db.insert_messages([message]), {"inserted": 0, "skipped": 1})

    def test_insert_attachment_saves_archive_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Kei",
                "sent_at": "2026-06-10 18:00",
                "text": "完成",
                "message_fingerprint": "b" * 64,
                "has_attachments": True,
                "attachment_hints": [],
                "raw_payload": {},
            }
            db.insert_messages([message])
            stored = db.get_message_by_fingerprint("b" * 64)

            inserted = db.insert_attachment(
                {
                    "raw_message_id": stored["id"],
                    "original_filename": "photo.jpg",
                    "original_path": "/tmp/photo.jpg",
                    "archive_filename": "2026-06-10_site_Kei_work_image_abcd.jpg",
                    "archive_path": "archive/2026/06/site/2026-06-10_site_Kei_work_image_abcd.jpg",
                    "attachment_type": "image",
                    "sha256": "c" * 64,
                    "size_bytes": 12,
                }
            )

            self.assertTrue(inserted)
            attachments = db.list_attachments_for_message(stored["id"])
            self.assertEqual(attachments[0]["archive_filename"], "2026-06-10_site_Kei_work_image_abcd.jpg")

    def test_download_jobs_wait_for_analysis_done(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Kei",
                "sent_at": "2026-06-10T18:00:00+08:00",
                "text": "完成，附相",
                "message_fingerprint": "j" * 64,
                "has_attachments": True,
                "attachment_hints": [{"type": "image"}],
                "raw_payload": {},
            }
            db.insert_messages([message])
            stored = db.get_message_by_fingerprint("j" * 64)

            self.assertEqual(db.list_download_jobs(), [])

            db.mark_message_done(stored["id"])
            record_id = db.save_repair_record(
                stored["id"],
                {
                    "work_date": "2026-06-10",
                    "staff_name": "Kei",
                    "site": "商场A",
                    "work_type": "maintenance",
                    "summary": "完成，附相",
                    "completion_status": "已完成",
                },
            )
            jobs = db.list_download_jobs()

            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["message_fingerprint"], "j" * 64)
            self.assertEqual(jobs[0]["site"], "商场A")
            self.assertEqual(jobs[0]["staff_name"], "Kei")
            self.assertEqual(jobs[0]["work_type"], "maintenance")
            self.assertEqual(jobs[0]["work_date"], "2026-06-10")
            self.assertIsInstance(record_id, int)

    def test_download_jobs_skip_unknown_site(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Kei",
                "sent_at": "2026-06-10T18:00:00+08:00",
                "text": "完成，附相",
                "message_fingerprint": "k" * 64,
                "has_attachments": True,
                "attachment_hints": [{"type": "image"}],
                "raw_payload": {},
            }
            db.insert_messages([message])
            stored = db.get_message_by_fingerprint("k" * 64)
            db.save_repair_record(
                stored["id"],
                {
                    "work_date": "2026-06-10",
                    "staff_name": "Kei",
                    "site": "",
                    "work_type": "maintenance",
                    "summary": "完成，附相",
                    "completion_status": "已完成",
                },
            )
            db.mark_message_done(stored["id"])

            self.assertEqual(db.list_download_jobs(), [])

    def test_download_jobs_keep_message_until_all_attachment_types_are_uploaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Kei",
                "sent_at": "2026-06-10T18:00:00+08:00",
                "text": "完成，附相及 PDF",
                "message_fingerprint": "kp" * 32,
                "has_attachments": True,
                "attachment_hints": [{"type": "image"}, {"type": "pdf"}],
                "raw_payload": {},
            }
            db.insert_messages([message])
            stored = db.get_message_by_fingerprint("kp" * 32)
            db.mark_message_done(stored["id"])
            db.save_repair_record(
                stored["id"],
                {
                    "work_date": "2026-06-10",
                    "staff_name": "Kei",
                    "site": "商场A",
                    "work_type": "maintenance",
                    "summary": "完成，附相及 PDF",
                    "completion_status": "已完成",
                },
            )

            initial_jobs = db.list_download_jobs()
            self.assertEqual(len(initial_jobs), 1)
            self.assertEqual(initial_jobs[0]["missing_attachment_types"], ["image", "pdf"])

            db.insert_attachment(
                {
                    "raw_message_id": stored["id"],
                    "original_filename": "photo.jpg",
                    "original_path": "/tmp/photo.jpg",
                    "archive_filename": "2026-06-10_site_Kei_work_image_abcd.jpg",
                    "archive_path": "archive/2026/06/site/2026-06-10_site_Kei_work_image_abcd.jpg",
                    "attachment_type": "image",
                    "sha256": "d" * 64,
                    "size_bytes": 12,
                }
            )

            followup_jobs = db.list_download_jobs()
            self.assertEqual(len(followup_jobs), 1)
            self.assertEqual(followup_jobs[0]["missing_attachment_types"], ["pdf"])

            db.insert_attachment(
                {
                    "raw_message_id": stored["id"],
                    "original_filename": "report.pdf",
                    "original_path": "/tmp/report.pdf",
                    "archive_filename": "2026-06-10_site_Kei_work_pdf_abcd.pdf",
                    "archive_path": "archive/2026/06/site/2026-06-10_site_Kei_work_pdf_abcd.pdf",
                    "attachment_type": "pdf",
                    "sha256": "e" * 64,
                    "size_bytes": 24,
                }
            )

            self.assertEqual(db.list_download_jobs(), [])

    def test_get_message_by_external_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Kei",
                "sent_at": "2026-06-10 18:00",
                "text": "完成",
                "message_fingerprint": "x" * 64,
                "external_message_id": "yingdao_20260610_1800_kei_done",
                "has_attachments": False,
                "attachment_hints": [],
                "raw_payload": {},
            }

            db.insert_messages([message])
            stored = db.get_message_by_external_id("yingdao_20260610_1800_kei_done")

            self.assertIsNotNone(stored)
            self.assertEqual(stored["message_fingerprint"], "x" * 64)

    def test_run_records_are_saved_and_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()

            run_id = db.save_run_record(
                {
                    "run_id": "run_test",
                    "run_type": "mock_message",
                    "status": "success",
                    "sender": "Sam",
                    "message_summary": "完成但 PDF 后补",
                    "message_fingerprint": "d" * 64,
                    "mock_feishu_record_id": "mock_rec_1",
                    "inserted_count": 1,
                    "analyzed_count": 1,
                    "feishu_synced_count": 1,
                    "reminders_created": 1,
                }
            )

            self.assertEqual(run_id, "run_test")
            self.assertEqual(db.get_run_record("run_test")["sender"], "Sam")
            self.assertEqual(db.list_run_records(1)[0]["mock_feishu_record_id"], "mock_rec_1")

    def test_task_events_are_saved_and_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            saved = db.save_task_event(
                {
                    "event_type": "followup_missing_pdf",
                    "sender": "Henry atl",
                    "target_name": "Brian",
                    "site": "商场26",
                    "work_date": "2026-05-22",
                    "event_text": "@Brian 请补维修报告 PDF",
                    "event_payload": {"missing_items": ["维修报告 PDF"]},
                }
            )

            self.assertTrue(saved["inserted"])
            events = db.list_task_events(1)
            self.assertEqual(events[0]["event_type"], "followup_missing_pdf")
            self.assertEqual(events[0]["event_payload"]["missing_items"], ["维修报告 PDF"])

    def test_list_repair_records_needing_followup_decodes_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Casey",
                "sent_at": "2026-06-10 13:00",
                "text": "商场C 已处理，维修报告 PDF 后补。",
                "message_fingerprint": "e" * 64,
                "has_attachments": False,
                "attachment_hints": [],
                "raw_payload": {},
            }
            db.insert_messages([message])
            stored = db.get_message_by_fingerprint("e" * 64)
            db.save_repair_record(
                stored["id"],
                {
                    "work_date": "2026-06-10",
                    "staff_name": "Casey",
                    "site": "商场C",
                    "work_type": "maintenance",
                    "summary": "已处理，维修报告 PDF 后补。",
                    "completion_status": "资料不足",
                    "completion_score": 78,
                    "completion_level": "较高",
                    "missing_items": ["维修报告 PDF"],
                    "next_actions": ["提醒补充维修报告 PDF"],
                },
            )

            records = db.list_repair_records_needing_followup(work_date="2026-06-10", limit=10)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["staff_name"], "Casey")
            self.assertEqual(records[0]["completion_score"], 78)
            self.assertEqual(records[0]["completion_level"], "较高")
            self.assertEqual(records[0]["missing_items"], ["维修报告 PDF"])
            self.assertEqual(records[0]["next_actions"], ["提醒补充维修报告 PDF"])
            self.assertEqual(records[0]["whatsapp_sender"], "Casey")
            self.assertEqual(records[0]["whatsapp_text"], "商场C 已处理，维修报告 PDF 后补。")

    def test_create_reminder_formats_ai_content_with_whatsapp_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Casey",
                "sent_at": "2026-06-10 13:00",
                "text": "商场C 已处理，维修报告 PDF 后补。",
                "message_fingerprint": "r" * 64,
                "has_attachments": False,
                "attachment_hints": [],
                "raw_payload": {},
            }
            db.insert_messages([message])
            stored = db.get_message_by_fingerprint("r" * 64)
            record_id = db.save_repair_record(
                stored["id"],
                {
                    "work_date": "2026-06-10",
                    "staff_name": "Casey",
                    "site": "商场C",
                    "summary": "维修报告 PDF 后补",
                    "completion_status": "资料不足",
                    "missing_items": ["维修报告 PDF"],
                },
            )

            created = db.create_reminder_if_needed(
                record_id,
                {
                    "staff_name": "Casey",
                    "completion_status": "资料不足",
                    "missing_items": ["维修报告 PDF"],
                    "next_actions": [],
                    "reminder_text": "@Casey 請補維修報告掃描",
                    "whatsapp_text": "商场C 已处理，维修报告 PDF 后补。",
                },
            )

            self.assertTrue(created)
            reminder = db.list_pending_reminders()[0]
            self.assertEqual(
                reminder["content"],
                "@Casey 請補維修報告掃描\n\n-------\n\n商场C 已处理，维修报告 PDF 后补。",
            )

    def test_create_reminder_skips_completed_and_plain_pending_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            db.insert_messages([
                {
                    "group_name": "维修群",
                    "sender": "Casey",
                    "sent_at": "2026-06-10 13:00",
                    "text": "完成",
                    "message_fingerprint": "s" * 64,
                    "has_attachments": False,
                    "attachment_hints": [],
                    "raw_payload": {},
                },
                {
                    "group_name": "维修群",
                    "sender": "Casey",
                    "sent_at": "2026-06-10 14:00",
                    "text": "待确认",
                    "message_fingerprint": "t" * 64,
                    "has_attachments": False,
                    "attachment_hints": [],
                    "raw_payload": {},
                },
            ])
            first_message = db.get_message_by_fingerprint("s" * 64)
            second_message = db.get_message_by_fingerprint("t" * 64)
            first_id = db.save_repair_record(
                first_message["id"],
                {"staff_name": "Casey", "summary": "完成", "completion_status": "已完成"},
            )
            second_id = db.save_repair_record(
                second_message["id"],
                {"staff_name": "Casey", "summary": "待确认但无缺失", "completion_status": "待人工确认"},
            )

            self.assertFalse(
                db.create_reminder_if_needed(
                    first_id,
                    {"staff_name": "Casey", "completion_status": "已完成", "missing_items": [], "next_actions": []},
                )
            )
            self.assertFalse(
                db.create_reminder_if_needed(
                    second_id,
                    {"staff_name": "Casey", "completion_status": "待人工确认", "missing_items": [], "next_actions": []},
                )
            )
            self.assertEqual(db.list_pending_reminders(), [])

    def test_create_reminder_requires_target_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            db.insert_messages([
                {
                    "group_name": "维修群",
                    "sender": "Casey",
                    "sent_at": "2026-06-10 13:00",
                    "text": "缺 PDF",
                    "message_fingerprint": "w" * 64,
                    "has_attachments": False,
                    "attachment_hints": [],
                    "raw_payload": {},
                }
            ])
            message = db.get_message_by_fingerprint("w" * 64)
            record_id = db.save_repair_record(
                message["id"],
                {"staff_name": "Casey", "summary": "缺 PDF", "completion_status": "资料不足"},
            )

            self.assertFalse(
                db.create_reminder_if_needed(
                    record_id,
                    {
                        "staff_name": "",
                        "completion_status": "资料不足",
                        "missing_items": ["维修报告 PDF"],
                        "next_actions": [],
                        "reminder_text": "@Casey 请补维修报告扫描",
                    },
                )
            )
            self.assertFalse(
                db.create_reminder_if_needed(
                    record_id,
                    {
                        "staff_name": "Casey",
                        "completion_status": "资料不足",
                        "missing_items": ["维修报告 PDF"],
                        "next_actions": [],
                        "reminder_text": "",
                    },
                )
            )
            self.assertEqual(db.list_pending_reminders(), [])

    def test_create_reminder_deduplicates_same_pending_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            db.insert_messages([
                {
                    "group_name": "维修群",
                    "sender": "Casey",
                    "sent_at": "2026-06-10 13:00",
                    "text": "缺 PDF",
                    "message_fingerprint": "u" * 64,
                    "has_attachments": False,
                    "attachment_hints": [],
                    "raw_payload": {},
                },
                {
                    "group_name": "维修群",
                    "sender": "Casey",
                    "sent_at": "2026-06-10 14:00",
                    "text": "缺 PDF",
                    "message_fingerprint": "v" * 64,
                    "has_attachments": False,
                    "attachment_hints": [],
                    "raw_payload": {},
                },
            ])
            first_message = db.get_message_by_fingerprint("u" * 64)
            second_message = db.get_message_by_fingerprint("v" * 64)
            first_id = db.save_repair_record(
                first_message["id"],
                {"staff_name": "Casey", "site": "商场C", "summary": "缺 PDF", "completion_status": "资料不足"},
            )
            second_id = db.save_repair_record(
                second_message["id"],
                {"staff_name": "Casey", "site": "商场C", "summary": "缺 PDF", "completion_status": "资料不足"},
            )
            analysis = {
                "staff_name": "Casey",
                "completion_status": "资料不足",
                "missing_items": ["维修报告 PDF"],
                "next_actions": [],
                "reminder_text": "@Casey 請補維修報告掃描",
            }

            self.assertTrue(db.create_reminder_if_needed(first_id, analysis))
            self.assertFalse(db.create_reminder_if_needed(second_id, analysis))
            self.assertEqual(len(db.list_pending_reminders()), 1)

    def test_export_repair_records_normalizes_yingdao_sent_at_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Casey",
                "sent_at": "25/6/2026 上午10:51",
                "text": "The SOUI TV wall 正常",
                "message_fingerprint": "y" * 64,
                "has_attachments": False,
                "attachment_hints": [],
                "raw_payload": {},
            }
            db.insert_messages([message])
            stored = db.get_message_by_fingerprint("y" * 64)
            db.save_repair_record(
                stored["id"],
                {
                    "work_date": "2026-06-25",
                    "staff_name": "Casey",
                    "site": "The SOUI",
                    "work_type": "maintenance",
                    "summary": "TV wall 正常",
                    "completion_status": "已完成",
                    "completion_score": 100,
                    "completion_level": "高",
                    "missing_items": [],
                    "next_actions": [],
                },
            )

            records = db.list_export_repair_records("2026-06-25")

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["export_date"], "2026-06-25")
            self.assertEqual(records[0]["site"], "The SOUI")

    def test_save_repair_record_allows_multiple_items_per_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Casey",
                "sent_at": "2026-06-10 13:00",
                "text": "TV wall 正常\nLG08 更换火牛后正常",
                "message_fingerprint": "f" * 64,
                "has_attachments": False,
                "attachment_hints": [],
                "raw_payload": {},
            }
            db.insert_messages([message])
            stored = db.get_message_by_fingerprint("f" * 64)

            first = db.save_repair_record(
                stored["id"],
                {
                    "work_date": "2026-06-10",
                    "staff_name": "Casey",
                    "site": "The SOUI",
                    "work_type": "maintenance",
                    "summary": "TV wall 重新 config 后正常",
                    "completion_status": "已完成",
                },
                "mock_rec_first",
                item_index=0,
            )
            second = db.save_repair_record(
                stored["id"],
                {
                    "work_date": "2026-06-10",
                    "staff_name": "Casey",
                    "site": "The SOUI LG08",
                    "work_type": "maintenance",
                    "summary": "电子门更换火牛后正常",
                    "completion_status": "已完成",
                },
                "mock_rec_second",
                item_index=1,
            )

            self.assertNotEqual(first, second)
            self.assertEqual(len(db.list_repair_records_needing_followup(limit=10)), 0)
            records = db.list_repair_records_for_message(stored["id"])
            self.assertEqual([record["item_index"] for record in records], [0, 1])
            self.assertEqual(records[1]["site"], "The SOUI LG08")

    def test_delete_repair_records_for_message_removes_mock_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            message = {
                "group_name": "维修群",
                "sender": "Casey",
                "sent_at": "2026-06-10 13:00",
                "text": "料",
                "message_fingerprint": "0" * 64,
                "has_attachments": False,
                "attachment_hints": [],
                "raw_payload": {},
            }
            db.insert_messages([message])
            stored = db.get_message_by_fingerprint("0" * 64)
            mock_id = db.save_mock_feishu_record({"AI摘要": "脏记录"})
            db.save_repair_record(
                stored["id"],
                {
                    "work_date": "2026-06-10",
                    "staff_name": "Casey",
                    "summary": "料",
                    "completion_status": "资料不足",
                },
                mock_id,
            )

            self.assertEqual(db.delete_repair_records_for_message(stored["id"]), 1)
            self.assertEqual(db.list_mock_feishu_records(limit=10), [])

    def test_cleanup_mock_records_by_whatsapp_texts_removes_label_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            keep_id = db.save_mock_feishu_record({"WhatsApp原文": "G807 更换对讲机"})
            drop_id = db.save_mock_feishu_record({"WhatsApp原文": "後"})

            result = db.cleanup_mock_records_by_whatsapp_texts({"後", "中"})

            self.assertEqual(result["mock_records_deleted"], 1)
            records = db.list_mock_feishu_records(limit=10)
            self.assertEqual([record["record_id"] for record in records], [keep_id])
            self.assertNotEqual(keep_id, drop_id)

    def test_resolve_staff_name_uses_active_staff_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            db.upsert_staff_config(
                {
                    "name": "Brian",
                    "whatsapp_name": "num5",
                    "aliases": ["強"],
                    "feishu_name": "Brian 強",
                    "roles": ["technician"],
                    "is_active": True,
                }
            )

            self.assertEqual(db.resolve_staff_name("num5"), "Brian 強")
            self.assertEqual(db.resolve_staff_name("強"), "Brian 強")
            self.assertEqual(db.resolve_staff_name("unknown"), "unknown")

    def test_site_config_aliases_are_matched_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            site_id = db.upsert_site_config(
                {
                    "name": "LPP",
                    "aliases": ["LPP Free Access", "L212D", "L322"],
                    "notes": "LPP 内部门点",
                    "is_active": True,
                }
            )

            self.assertGreater(site_id, 0)
            self.assertEqual(db.resolve_site_name("L212D"), "LPP")
            self.assertEqual(db.match_site_in_text("L322 Project Room red light")["name"], "LPP")
            self.assertTrue(db.set_site_active(site_id, False))
            self.assertIsNone(db.match_site_in_text("L322 Project Room red light"))

    def test_init_repairs_reminders_foreign_key_to_old_repair_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            with db.connect() as conn:
                conn.execute("ALTER TABLE reminders RENAME TO reminders_broken")
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
                        FOREIGN KEY(repair_record_id) REFERENCES repair_records_old(id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute("DROP TABLE reminders_broken")

            db.init()

            with db.connect() as conn:
                foreign_tables = {
                    row["table"] for row in conn.execute("PRAGMA foreign_key_list(reminders)").fetchall()
                }
            self.assertEqual(foreign_tables, {"repair_records"})

    def test_staff_role_config_is_saved_and_used_for_role_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()

            staff_id = db.upsert_staff_config(
                {
                    "name": "Dicky",
                    "whatsapp_name": "Dicky Company",
                    "aliases": ["Dicky C"],
                    "roles": ["dispatch_manager", "viewer"],
                    "is_active": True,
                    "notes": "主要派工",
                }
            )

            self.assertGreater(staff_id, 0)
            staff = db.list_staff_configs()
            self.assertEqual(staff[0]["roles"], ["dispatch_manager", "viewer"])
            self.assertEqual(
                db.list_staff_names_for_role("dispatch_manager"),
                ["Dicky Company", "Dicky C"],
            )
            self.assertTrue(db.set_staff_active(staff_id, False))
            self.assertEqual(db.list_staff_names_for_role("dispatch_manager"), [])

    def test_staff_config_can_be_updated_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            staff_id = db.upsert_staff_config(
                {
                    "name": "Tom",
                    "whatsapp_name": "Tom Company",
                    "aliases": [],
                    "roles": ["viewer"],
                    "is_active": True,
                }
            )

            updated_id = db.upsert_staff_config(
                {
                    "id": staff_id,
                    "name": "Tom",
                    "whatsapp_name": "Tom Company",
                    "aliases": [],
                    "roles": ["followup_manager"],
                    "is_active": True,
                    "notes": "changed role",
                }
            )
            staff = db.list_staff_configs()

            self.assertEqual(updated_id, staff_id)
            self.assertEqual(len(staff), 1)
            self.assertEqual(staff[0]["roles"], ["followup_manager"])
            self.assertEqual(staff[0]["notes"], "changed role")

    def test_system_principles_are_seeded_and_updated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()

            principles = {item["key"]: item["value"] for item in db.list_system_principles()}
            self.assertIn("task_source_policy", principles)

            db.update_system_principles({"unconfirmed_issue_reminder_hours": 12})
            updated = {item["key"]: item["value"] for item in db.list_system_principles()}

            self.assertEqual(updated["unconfirmed_issue_reminder_hours"], 12)

    def test_issue_record_can_be_converted_to_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            saved = db.save_issue_record(
                {
                    "raw_message_id": None,
                    "reported_by": "Brian",
                    "work_date": "2026-06-12",
                    "site": "商场41",
                    "issue_text": "商场41 CCTV mon 又闪",
                    "issue_summary": "商场41 CCTV mon 又闪",
                    "confidence": 0.85,
                }
            )

            result = db.convert_issue_to_schedule(
                saved["id"],
                {
                    "work_date": "2026-06-13",
                    "staff_name": "Lin",
                    "site": "商场41",
                    "task_text": "检查 CCTV mon 闪烁问题",
                    "source_file": f"issue_record:{saved['id']}",
                    "review_status": "confirmed",
                },
                note="确认安排",
            )
            issues = db.list_issue_records(status="converted", limit=10)

            self.assertTrue(result["converted"])
            self.assertEqual(issues[0]["status"], "converted")
            self.assertEqual(issues[0]["converted_work_schedule_id"], result["work_schedule_id"])

    def test_issue_record_status_can_be_updated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            saved = db.save_issue_record(
                {
                    "raw_message_id": None,
                    "reported_by": "Brian",
                    "work_date": "2026-06-12",
                    "site": "商场41",
                    "issue_text": "商场41 CCTV mon 又闪",
                    "issue_summary": "商场41 CCTV mon 又闪",
                    "confidence": 0.85,
                }
            )

            self.assertTrue(db.update_issue_status(saved["id"], "ignored", "重复问题"))
            issues = db.list_issue_records(status="ignored", limit=10)

            self.assertEqual(issues[0]["decision_note"], "重复问题")

    def test_issue_record_can_be_linked_to_existing_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            saved = db.save_issue_record(
                {
                    "raw_message_id": None,
                    "reported_by": "Brian",
                    "work_date": "2026-06-12",
                    "site": "商场41",
                    "issue_text": "商场41 CCTV mon 又闪",
                    "issue_summary": "商场41 CCTV mon 又闪",
                    "confidence": 0.85,
                }
            )
            db.insert_schedule_rows(
                [
                    {
                        "work_date": "2026-06-13",
                        "staff_name": "Lin",
                        "site": "商场41",
                        "task_text": "检查控制室 CCTV mon 闪烁问题",
                        "source_file": "whatsapp_dispatch:test",
                        "review_status": "confirmed",
                    }
                ]
            )
            schedule = db.find_schedule_row(
                {
                    "work_date": "2026-06-13",
                    "staff_name": "Lin",
                    "site": "商场41",
                    "task_text": "检查控制室 CCTV mon 闪烁问题",
                    "source_file": "whatsapp_dispatch:test",
                }
            )

            result = db.link_issue_to_schedule(saved["id"], schedule["id"], "自动匹配")
            issues = db.list_issue_records(status="converted", limit=10)

            self.assertTrue(result["linked"])
            self.assertEqual(issues[0]["converted_work_schedule_id"], schedule["id"])
            self.assertEqual(issues[0]["decision_note"], "自动匹配")

    def test_list_download_jobs_can_filter_by_group_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            db.insert_messages(
                [
                    {
                        "group_name": "群A",
                        "sender": "Kei",
                        "sent_at": "2026-06-10T18:00:00+08:00",
                        "text": "群A 完成，附 PDF",
                        "message_fingerprint": "ga" * 32,
                        "has_attachments": True,
                        "attachment_hints": [{"type": "pdf"}],
                        "raw_payload": {},
                    },
                    {
                        "group_name": "群B",
                        "sender": "Kei",
                        "sent_at": "2026-06-10T18:10:00+08:00",
                        "text": "群B 完成，附 PDF",
                        "message_fingerprint": "gb" * 32,
                        "has_attachments": True,
                        "attachment_hints": [{"type": "pdf"}],
                        "raw_payload": {},
                    },
                ]
            )
            message_a = db.get_message_by_fingerprint("ga" * 32)
            message_b = db.get_message_by_fingerprint("gb" * 32)
            db.mark_message_done(message_a["id"])
            db.mark_message_done(message_b["id"])
            db.save_repair_record(
                message_a["id"],
                {"work_date": "2026-06-10", "staff_name": "Kei", "site": "淺水灣", "summary": "群A", "completion_status": "已完成"},
            )
            db.save_repair_record(
                message_b["id"],
                {"work_date": "2026-06-10", "staff_name": "Kei", "site": "LPP", "summary": "群B", "completion_status": "已完成"},
            )

            jobs = db.list_download_jobs(group_name="群A")

            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["group_name"], "群A")

    def test_automation_runs_can_be_upserted_claimed_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            jobs = [
                {
                    "group_id": "group_a",
                    "group_name": "群A",
                    "job_type": "scan_cycle",
                    "scheduled_for": "2026-06-27T10:00:00+08:00",
                    "timezone": "Asia/Hong_Kong",
                    "site_names": ["淺水灣"],
                    "actions": ["collect_messages", "download_attachments"],
                    "skip_if_previous_scan_running": True,
                    "max_reminders_per_event_per_day": 2,
                    "skip_completed_events": True,
                }
            ]

            db.upsert_automation_jobs(jobs)
            db.upsert_automation_jobs(jobs)
            candidates = db.list_automation_run_candidates()
            claimed = db.claim_automation_run(candidates[0]["id"], "token_12345678")
            saved = db.save_automation_run_result(
                run_token="token_12345678",
                status="success",
                result_payload={"messages_posted": 5},
            )
            rows = db.list_automation_runs(limit=5)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(claimed["status"], "claimed")
            self.assertTrue(saved)
            self.assertEqual(rows[0]["status"], "succeeded")
            self.assertEqual(rows[0]["result_payload"], {"messages_posted": 5})

    def test_stale_automation_run_can_be_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            db.upsert_automation_jobs(
                [
                    {
                        "group_id": "group_a",
                        "group_name": "群A",
                        "job_type": "scan_cycle",
                        "scheduled_for": "2026-06-27T10:00:00+08:00",
                        "timezone": "Asia/Hong_Kong",
                        "site_names": [],
                        "actions": ["collect_messages"],
                        "skip_if_previous_scan_running": True,
                        "max_reminders_per_event_per_day": 1,
                        "skip_completed_events": True,
                    }
                ]
            )
            candidate = db.list_automation_run_candidates(limit=1)[0]
            db.claim_automation_run(candidate["id"], "token_old")

            changed = db.mark_stale_automation_runs("9999-12-31T23:59:59+00:00")
            reclaimed = db.claim_automation_run(candidate["id"], "token_new")

            self.assertEqual(changed, 1)
            self.assertEqual(reclaimed["run_token"], "token_new")
            self.assertEqual(reclaimed["status"], "claimed")

    def test_pending_reminders_can_filter_by_site_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "test.db")
            db.init()
            db.insert_messages(
                [
                    {
                        "group_name": "维修群",
                        "sender": "Casey",
                        "sent_at": "2026-06-10 13:00",
                        "text": "淺水灣 缺 PDF",
                        "message_fingerprint": "ra" * 32,
                        "has_attachments": False,
                        "attachment_hints": [],
                        "raw_payload": {},
                    },
                    {
                        "group_name": "维修群",
                        "sender": "Casey",
                        "sent_at": "2026-06-10 14:00",
                        "text": "LPP 缺照片",
                        "message_fingerprint": "rb" * 32,
                        "has_attachments": False,
                        "attachment_hints": [],
                        "raw_payload": {},
                    },
                ]
            )
            first_message = db.get_message_by_fingerprint("ra" * 32)
            second_message = db.get_message_by_fingerprint("rb" * 32)
            first_id = db.save_repair_record(
                first_message["id"],
                {"staff_name": "Casey", "site": "淺水灣", "summary": "缺 PDF", "completion_status": "资料不足"},
            )
            second_id = db.save_repair_record(
                second_message["id"],
                {"staff_name": "Casey", "site": "LPP", "summary": "缺照片", "completion_status": "资料不足"},
            )
            db.create_reminder_if_needed(
                first_id,
                {
                    "staff_name": "Casey",
                    "completion_status": "资料不足",
                    "missing_items": ["维修报告 PDF"],
                    "next_actions": [],
                    "reminder_text": "@Casey 请补 PDF",
                },
            )
            db.create_reminder_if_needed(
                second_id,
                {
                    "staff_name": "Casey",
                    "completion_status": "资料不足",
                    "missing_items": ["现场照片"],
                    "next_actions": [],
                    "reminder_text": "@Casey 请补照片",
                },
            )

            reminders = db.list_pending_reminders(site_names=["淺水灣"])

            self.assertEqual(len(reminders), 1)
            self.assertEqual(reminders[0]["site"], "淺水灣")


if __name__ == "__main__":
    unittest.main()
