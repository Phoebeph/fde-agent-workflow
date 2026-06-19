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


if __name__ == "__main__":
    unittest.main()
